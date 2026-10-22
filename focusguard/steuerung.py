"""Steuerung: verbindet Sensoren, Entscheider, Eskalation, Blocker, KI-Richter, Speicher und Oberfläche.

Läuft im Qt-Hauptthread; Sensoren und KI-Arbeiter liefern über thread-sichere Warteschlangen zu.
"""

from __future__ import annotations

import math
import queue
from typing import Callable, Protocol

from .auswertung import Auswertung, berechne
from .clock import Uhr
from .config import Einstellungen
from .decision.judge import Entscheider
from .decision.memory import Gedaechtnis
from .escalation import Eskalation
from .models import (Begruessung, HandyBeobachtung, HandyOverlay, Hinweis, IconStatus, KiAnfrage, KiErgebnis,
                     OverlaySchliessen, OverlayZeigen, PcBeobachtung, Session, Sperren, Status,
                     WebcamBeobachtung, AufgabenListen, aufgabe_key)
from .sensors.base import AUFGEGEBEN
from .storage import Speicher

KEINE_SESSION = "FocusGuard – keine Session"


class OberflaechePort(Protocol):
    def hinweis(self, text: str) -> None: ...
    def overlay_zeigen(self, titel: str, text: str, quelle: str) -> None: ...
    def overlay_schliessen(self) -> None: ...
    def icon(self, farbe: str) -> None: ...
    def tooltip(self, text: str) -> None: ...
    def zeige_auswertung(self, a: Auswertung, verlauf: list[Auswertung]) -> None: ...


class SensorPort(Protocol):
    def setze(self, pc: bool, webcam: bool, smartphone: bool) -> None: ...
    def stoppe(self) -> None: ...
    def problem(self) -> str | None: ...
    def kamera_jpeg(self) -> bytes | None: ...


class BlockerPort(Protocol):
    def pruefe(self, b: PcBeobachtung, gesperrt: frozenset[str], fokus: AufgabenListen) -> str | None: ...


class KiRichterPort(Protocol):
    def einreihen(self, anfrage: KiAnfrage, aufgabe: str) -> None: ...
    def leeren(self) -> None: ...
    def setze_bildschirm_pause(self, an: bool) -> None: ...


def _leere(q: queue.SimpleQueue) -> list:
    eintraege = []
    while True:
        try:
            eintraege.append(q.get_nowait())
        except queue.Empty:
            return eintraege


class Steuerung:
    def __init__(self, einst: Einstellungen, speicher: Speicher, ui: OberflaechePort,
                 sensoren_fabrik: Callable[[Callable[[object], None], Callable[[str, str], None]], SensorPort],
                 blocker: BlockerPort, richter: KiRichterPort | None, uhr: Uhr):
        self._einst = einst
        self._speicher = speicher
        self._ui = ui
        self._sensoren_fabrik = sensoren_fabrik
        self._blocker = blocker
        self._richter = richter
        self._uhr = uhr
        s = einst.sensoren
        self._sensoren_zustand = (s.pc, s.webcam, s.smartphone)

        self._beobachtungen: queue.SimpleQueue = queue.SimpleQueue()
        self._fehler: queue.SimpleQueue = queue.SimpleQueue()
        self._ki_ergebnisse: queue.SimpleQueue = queue.SimpleQueue()

        self._session: Session | None = None
        self._sitzung_einst = einst
        self._entscheider: Entscheider | None = None
        self._eskalation: Eskalation | None = None
        self._sensoren: SensorPort | None = None
        self._gesperrt: set[str] = set()
        self._offene_anfragen: dict[int, KiAnfrage] = {}
        self._letzter_status: tuple[Status, str] | None = None
        self._letzter_tooltip: str | None = None
        self._sensor_aus: list[str] = []

    # --- Zustand -------------------------------------------------------------------------------

    @property
    def aktiv(self) -> bool:
        return self._session is not None

    @property
    def aufgabe(self) -> str | None:
        return self._session.aufgabe if self._session else None

    @property
    def sensoren(self) -> tuple[bool, bool, bool]:
        return self._sensoren_zustand

    def setze_einstellungen(self, einst: Einstellungen) -> None:
        self._einst = einst

    # --- thread-sichere Eingänge ---------------------------------------------------------------

    def beobachtung(self, b: object) -> None:
        self._beobachtungen.put(b)

    def sensor_fehler(self, name: str, meldung: str) -> None:
        self._fehler.put((name, meldung))

    def ki_ergebnis(self, e: KiErgebnis) -> None:
        self._ki_ergebnisse.put(e)

    def kamera_jpeg(self) -> bytes | None:
        sensoren = self._sensoren
        return sensoren.kamera_jpeg() if sensoren is not None else None

    def aktuelle_pc(self) -> PcBeobachtung | None:
        """Thread-sicher lesbar: das zuletzt beobachtete Vordergrundfenster der laufenden Session."""
        entscheider = self._entscheider
        return entscheider.letzte_pc if entscheider is not None else None

    def _bildschirm_pause(self, an: bool) -> None:
        if self._richter is not None:
            self._richter.setze_bildschirm_pause(an)

    # --- Session -------------------------------------------------------------------------------

    def _ereignis(self, art: str, quelle: str = "", status: str = "", details: dict | None = None,
                  zeit: float | None = None) -> None:
        if self._session is not None:
            self._speicher.ereignis(self._session.id, self._uhr() if zeit is None else zeit, art, quelle, status,
                                    details)

    def starte_session(self, aufgabe: str, dauer_min: int, listen: AufgabenListen) -> None:
        if self.aktiv:
            return
        jetzt = self._uhr()
        key = aufgabe_key(aufgabe)
        self._sitzung_einst = einst = self._einst
        self._speicher.speichere_listen(key, listen)
        gedaechtnis = Gedaechtnis(self._speicher.lade_gedaechtnis(key))
        session = Session(None, aufgabe, key, jetzt, dauer_min)
        session.id = self._speicher.neue_session(session)
        self._session = session
        self._entscheider = Entscheider(einst, key, listen, gedaechtnis, jetzt)
        self._entscheider.setze_sensoren(*self._sensoren_zustand)
        self._eskalation = Eskalation(einst.eskalation, einst.erkennung.begruessung_ab_minuten, jetzt)
        self._gesperrt = set()
        self._offene_anfragen = {}
        self._sensor_aus = []
        self._letzter_tooltip = None
        for q in (self._beobachtungen, self._fehler, self._ki_ergebnisse):
            _leere(q)
        self._letzter_status = (Status.FOKUS, "")
        self._ereignis("statuswechsel", "", Status.FOKUS.value, zeit=jetzt)
        self._sensoren = self._sensoren_fabrik(self.beobachtung, self.sensor_fehler)
        self._sensoren.setze(*self._sensoren_zustand)
        self._ui.icon("gruen")
        self._aktualisiere_tooltip(jetzt)

    def beende_session(self, vorzeitig: bool, zeigen: bool = True) -> None:
        if not self.aktiv:
            return
        jetzt = self._uhr()
        session = self._session
        if self._sensoren is not None:
            self._sensoren.stoppe()
        if self._richter is not None:
            self._richter.leeren()
        self._ui.overlay_schliessen()
        self._bildschirm_pause(False)
        self._gesperrt.clear()
        self._ui.icon("grau")
        self._ui.tooltip(KEINE_SESSION)
        self._letzter_tooltip = KEINE_SESSION
        self._speicher.beende_session(session.id, jetzt, vorzeitig)
        session.ende, session.vorzeitig_beendet = jetzt, vorzeitig
        auswertung = berechne(session, self._speicher.ereignisse(session.id), self._sitzung_einst.ki.modell, jetzt)
        self._session = None
        self._entscheider = None
        self._eskalation = None
        self._sensoren = None
        self._offene_anfragen = {}
        if not vorzeitig:
            self._ui.hinweis("Session geschafft!")
        if zeigen:
            self._ui.zeige_auswertung(auswertung, self.verlauf_7_tage())

    def verlauf_7_tage(self) -> list[Auswertung]:
        jetzt = self._uhr()
        return [berechne(s, self._speicher.ereignisse(s.id), self._einst.ki.modell, jetzt)
                for s in self._speicher.sessions_seit(jetzt - 7 * 86400)]

    def setze_sensoren(self, pc: bool, webcam: bool, smartphone: bool) -> None:
        self._sensoren_zustand = (pc, webcam, smartphone)
        if not self.aktiv:
            return
        self._entscheider.setze_sensoren(pc, webcam, smartphone)
        self._sensoren.setze(pc, webcam, smartphone)
        self._ereignis("checkbox", details={"pc": pc, "webcam": webcam, "smartphone": smartphone})

    # --- Bedienung -----------------------------------------------------------------------------

    def zurueck_zur_aufgabe(self) -> None:
        if not self.aktiv:
            return
        jetzt = self._uhr()
        for a in self._eskalation.zurueck_zur_aufgabe(jetzt):
            self._ausfuehren(a, "", jetzt)

    def gehoert_zur_aufgabe(self, quelle: str) -> None:
        if not self.aktiv:
            return
        jetzt = self._uhr()
        listen, eintrag = self._entscheider.korrektur(quelle, jetzt)
        if listen is not None:
            self._speicher.speichere_listen(self._session.aufgabe_key, listen)
        if eintrag is not None:
            self._speicher.speichere_gedaechtnis(eintrag)
        self._gesperrt.discard(quelle)
        for a in self._eskalation.korrektur(jetzt):
            self._ausfuehren(a, quelle, jetzt)
        self._ereignis("korrektur", quelle, zeit=jetzt)

    def sperren_aufheben(self) -> None:
        if not self.aktiv:
            return
        self._gesperrt.clear()
        self._ereignis("sperre_aufgehoben")

    # --- Takt ----------------------------------------------------------------------------------

    def tick(self) -> None:
        if not self.aktiv:
            for q in (self._beobachtungen, self._fehler, self._ki_ergebnisse):
                _leere(q)
            return
        jetzt = self._uhr()
        e = self._entscheider

        for b in _leere(self._beobachtungen):
            if isinstance(b, PcBeobachtung):
                e.pc(b)
                self._blockiere(b, jetzt)
            elif isinstance(b, WebcamBeobachtung):
                e.webcam(b)
            elif isinstance(b, HandyBeobachtung):
                e.handy(b)

        for name, meldung in _leere(self._fehler):
            self._ereignis("sensor_fehler", name, details={"meldung": meldung}, zeit=jetzt)
            zeile = f"{name}-Sensor ausgeschaltet"
            if meldung == AUFGEGEBEN and zeile not in self._sensor_aus:
                self._sensor_aus.append(zeile)

        for ergebnis in _leere(self._ki_ergebnisse):
            if self._offene_anfragen.pop(id(ergebnis.anfrage), None) is not ergebnis.anfrage:
                continue
            eintrag = e.ki_ergebnis(ergebnis, jetzt)
            if eintrag is not None:
                self._speicher.speichere_gedaechtnis(eintrag)
            self._ereignis("ki_aufruf", ergebnis.anfrage.quelle,
                           ergebnis.urteil.status.value if ergebnis.urteil else "",
                           {"art": ergebnis.anfrage.art.value, "tokens_ein": ergebnis.tokens_ein,
                            "tokens_aus": ergebnis.tokens_aus, "fehler": ergebnis.fehler}, zeit=jetzt)

        if self._richter is not None:
            for anfrage in e.ki_anfragen(jetzt):
                self._offene_anfragen[id(anfrage)] = anfrage
                self._richter.einreihen(anfrage, self._session.aufgabe)

        u = e.urteil(jetzt)
        if (u.status, u.quelle) != self._letzter_status:
            self._letzter_status = (u.status, u.quelle)
            self._ereignis("statuswechsel", u.quelle, u.status.value,
                           {"begruendung": u.begruendung, "herkunft": u.herkunft}, zeit=jetzt)

        for aktion in self._eskalation.schritt(u, jetzt):
            self._ausfuehren(aktion, u.quelle, jetzt)

        self._aktualisiere_tooltip(jetzt)
        if jetzt >= self._session.start + self._session.geplant_min * 60:
            self.beende_session(vorzeitig=False)

    def _blockiere(self, b: PcBeobachtung, jetzt: float) -> None:
        try:
            aktion = self._blocker.pruefe(b, frozenset(self._gesperrt), self._entscheider.listen)
        except Exception as fehler:
            aktion = "fehler"
            self._ereignis("sensor_fehler", "blocker", details={"meldung": repr(fehler)}, zeit=jetzt)
        if aktion:
            self._ereignis("sperre_ausgefuehrt", b.prozess, details={"aktion": aktion, "domain": b.domain},
                           zeit=jetzt)

    def _fokus_minuten(self, jetzt: float) -> int:
        a = berechne(self._session, self._speicher.ereignisse(self._session.id), self._sitzung_einst.ki.modell,
                     jetzt)
        return int(a.sekunden[Status.FOKUS] // 60)

    def _ausfuehren(self, aktion, quelle: str, jetzt: float) -> None:
        aufgabe = self._session.aufgabe
        if isinstance(aktion, Hinweis):
            self._ui.hinweis(f"{aktion.text} – zurück zu {aufgabe}?")
            self._ereignis("eskalation", quelle, Status.ABGELENKT.value, {"stufe": 1}, zeit=jetzt)
        elif isinstance(aktion, OverlayZeigen):
            text = f"{aktion.text}\nFokuszeit bisher: {self._fokus_minuten(jetzt)} min"
            self._ui.overlay_zeigen(f"Zurück zu: {aufgabe}", text, aktion.quelle)
            self._bildschirm_pause(True)
            self._ereignis("eskalation", aktion.quelle, Status.ABGELENKT.value, {"stufe": 2}, zeit=jetzt)
        elif isinstance(aktion, Sperren):
            self._gesperrt.add(aktion.quelle)
            self._ereignis("eskalation", aktion.quelle, Status.ABGELENKT.value, {"stufe": 3}, zeit=jetzt)
            self._ereignis("sperre", aktion.quelle, zeit=jetzt)
        elif isinstance(aktion, HandyOverlay):
            self._ui.overlay_zeigen("Leg das Handy weg", f"Zurück zu: {aufgabe}", "handy")
            self._bildschirm_pause(True)
            self._ereignis("eskalation", "handy", Status.ABGELENKT.value, {"stufe": 3}, zeit=jetzt)
        elif isinstance(aktion, OverlaySchliessen):
            self._ui.overlay_schliessen()
            self._bildschirm_pause(False)
        elif isinstance(aktion, Begruessung):
            self._ui.hinweis(f"Du warst {aktion.minuten_weg} Minuten weg. Weiter mit {aufgabe}?")
        elif isinstance(aktion, IconStatus):
            self._ui.icon(aktion.farbe)

    def _aktualisiere_tooltip(self, jetzt: float) -> None:
        s = self._session
        rest = max(0, math.ceil((s.start + s.geplant_min * 60 - jetzt) / 60))
        zeilen = [f"FocusGuard – {s.aufgabe} – noch {rest} min"]
        problem = self._sensoren.problem() if self._sensoren is not None else None
        if problem:
            zeilen.append(problem)
        zeilen += self._sensor_aus
        text = "\n".join(zeilen)
        if text != self._letzter_tooltip:
            self._letzter_tooltip = text
            self._ui.tooltip(text)
