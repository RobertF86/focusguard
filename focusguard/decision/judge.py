"""Der Entscheider fasst PC-, Kamera- und Stichproben-Urteile zu einem Gesamturteil zusammen
und entscheidet, wann die KI gefragt wird."""

from __future__ import annotations

import math

from ..config import Einstellungen
from ..models import (QUELLE_HANDY, QUELLE_STICHPROBE, AufgabenListen, GedaechtnisEintrag, HandyBeobachtung,
                      KiAnfrage, KiArt, KiErgebnis, PcBeobachtung, Status, Urteil, WebcamBeobachtung,
                      quelle_seite)
from .kamera_regeln import KameraBewerter
from .memory import Gedaechtnis, eintrag_fuer, quelle_fuer, seiten_schluessel
from .rules import regel_urteil

PC_VERALTET_S = 5.0
KI_FEHLER_PAUSE_S = 30.0
KI_UNKLAR_PAUSE_S = 300.0
HANDY_KORREKTUR_PAUSE_S = 120.0

_RANG = {Status.FOKUS: 0, Status.UNKLAR: 1, Status.ABWESEND: 2, Status.ABGELENKT: 3}
_NEUTRAL = Urteil(Status.FOKUS, "", "", "lokal")


def _hoechstes(urteile: list[Urteil | None]) -> Urteil:
    bestes = _NEUTRAL
    for u in urteile:
        if u is not None and _RANG[u.status] > _RANG[bestes.status]:
            bestes = u
    return bestes


class Entscheider:
    def __init__(self, einst: Einstellungen, aufgabe_key: str, listen: AufgabenListen,
                 gedaechtnis: Gedaechtnis, start: float):
        self._einst = einst
        self._aufgabe_key = aufgabe_key
        self._listen = listen
        self._gedaechtnis = gedaechtnis
        s = einst.sensoren
        self._pc_aktiv, self._webcam_aktiv, self._smartphone_aktiv = s.pc, s.webcam, s.smartphone
        self.kamera = KameraBewerter(einst.erkennung, einst.ki.handy_pruefung_sekunden, start,
                                     s.webcam, s.smartphone)
        self._letzte_pc: PcBeobachtung | None = None
        self._unterwegs: set[str] = set()
        self._naechster_versuch: dict[str, float] = {}

        self._sp_zustand = "ruhig"           # ruhig → verdacht → bestaetigt
        self._sp_naechste = start + einst.ki.stichprobe_sekunden
        self._sp_verdacht_start: float | None = None
        self._sp_begruendung = ""
        self._sp_bestaetigt_bis = -math.inf   # ohne neue Bestätigung endet die Stichproben-Ablenkung

    @property
    def listen(self) -> AufgabenListen:
        return self._listen

    @property
    def letzte_pc(self) -> PcBeobachtung | None:
        return self._letzte_pc

    def setze_sensoren(self, pc: bool, webcam: bool, smartphone: bool) -> None:
        self._pc_aktiv, self._webcam_aktiv, self._smartphone_aktiv = pc, webcam, smartphone
        self.kamera.setze_aktiv(webcam, smartphone)

    def pc(self, b: PcBeobachtung) -> None:
        self._letzte_pc = b

    def webcam(self, b: WebcamBeobachtung) -> None:
        self.kamera.webcam(b)

    def handy(self, b: HandyBeobachtung) -> None:
        self.kamera.handy(b)

    def _pc_urteil(self, jetzt: float) -> Urteil | None:
        b = self._letzte_pc
        if not self._pc_aktiv or b is None or jetzt - b.zeit > PC_VERALTET_S:
            return None
        u = regel_urteil(b, self._listen, self._einst.listen)
        if u is not None:
            return u
        e = self._gedaechtnis.suche(b)
        if e is not None:
            return Urteil(e.status, quelle_fuer(e), e.begruendung, "gedaechtnis")
        return Urteil(Status.UNKLAR, quelle_seite(seiten_schluessel(b)), "Noch nicht beurteilt", "lokal")

    def _stichprobe_urteil(self, jetzt: float) -> Urteil | None:
        if self._sp_zustand != "bestaetigt" or jetzt > self._sp_bestaetigt_bis:
            return None
        return Urteil(Status.ABGELENKT, QUELLE_STICHPROBE, self._sp_begruendung, "ki", seit=self._sp_verdacht_start)

    def urteil(self, jetzt: float) -> Urteil:
        return _hoechstes([self._pc_urteil(jetzt), self.kamera.urteil(jetzt), self._stichprobe_urteil(jetzt)])

    def ki_anfragen(self, jetzt: float) -> list[KiAnfrage]:
        neu: list[KiAnfrage] = []
        if self._sp_zustand == "bestaetigt" and jetzt > self._sp_bestaetigt_bis:
            self._stichprobe_zuruecksetzen(jetzt, KI_FEHLER_PAUSE_S)    # Nachprüfung überfällig: zu deinen Gunsten
        pc_u = self._pc_urteil(jetzt)
        if pc_u is not None and pc_u.status is Status.UNKLAR and pc_u.herkunft == "lokal":
            q = pc_u.quelle
            if q not in self._unterwegs and jetzt >= self._naechster_versuch.get(q, -math.inf):
                self._unterwegs.add(q)
                neu.append(KiAnfrage(KiArt.SEITE, q, jetzt, self._letzte_pc, True, False))

        if QUELLE_HANDY not in self._unterwegs and self.kamera.braucht_ki(jetzt):
            self.kamera.ki_angefragt(jetzt)
            self._unterwegs.add(QUELLE_HANDY)
            neu.append(KiAnfrage(KiArt.HANDY, QUELLE_HANDY, jetzt, None, False, True))

        kamera_an = self._webcam_aktiv or self._smartphone_aktiv
        if (QUELLE_STICHPROBE not in self._unterwegs and jetzt >= self._sp_naechste
                and (self._pc_aktiv or kamera_an)
                and _hoechstes([pc_u, self.kamera.urteil(jetzt)]).status is not Status.ABWESEND):
            self._unterwegs.add(QUELLE_STICHPROBE)
            neu.append(KiAnfrage(KiArt.STICHPROBE, QUELLE_STICHPROBE, jetzt,
                                 self._letzte_pc if self._pc_aktiv else None, self._pc_aktiv, kamera_an))
        return neu

    def ki_ergebnis(self, e: KiErgebnis, jetzt: float) -> GedaechtnisEintrag | None:
        a = e.anfrage
        self._unterwegs.discard(a.quelle)
        if a.art is KiArt.SEITE:
            if e.urteil is None:
                self._naechster_versuch[a.quelle] = jetzt + KI_FEHLER_PAUSE_S
                return None
            eintrag = eintrag_fuer(a.pc, e.urteil, self._aufgabe_key, jetzt)
            if eintrag is None:
                self._naechster_versuch[a.quelle] = jetzt + KI_UNKLAR_PAUSE_S
                return None
            self._gedaechtnis.merke(eintrag)
            return eintrag
        if a.art is KiArt.HANDY:
            self.kamera.ki_ergebnis(e.urteil, jetzt)
            return None
        self._stichprobe_ergebnis(a, e, jetzt)
        return None

    def _stichprobe_ergebnis(self, a: KiAnfrage, e: KiErgebnis, jetzt: float) -> None:
        if e.urteil is None:
            self._stichprobe_zuruecksetzen(jetzt, KI_FEHLER_PAUSE_S)    # KI nicht erreichbar: zu deinen Gunsten
            return
        if e.urteil.status is Status.ABGELENKT:
            if self._sp_zustand == "ruhig":
                self._sp_zustand = "verdacht"
                self._sp_verdacht_start = a.zeit
            elif self._sp_zustand == "verdacht":
                self._sp_zustand = "bestaetigt"
            self._sp_begruendung = e.urteil.begruendung
            self._sp_naechste = jetzt + self._einst.ki.stichprobe_nachpruefung_sekunden
            self._sp_bestaetigt_bis = jetzt + 2 * self._einst.ki.stichprobe_nachpruefung_sekunden
        else:
            self._stichprobe_zuruecksetzen(jetzt)

    def _stichprobe_zuruecksetzen(self, jetzt: float, pause_s: float | None = None) -> None:
        self._sp_zustand = "ruhig"
        self._sp_verdacht_start = None
        self._sp_naechste = jetzt + (self._einst.ki.stichprobe_sekunden if pause_s is None else pause_s)

    def korrektur(self, quelle: str, jetzt: float) -> tuple[AufgabenListen | None, GedaechtnisEintrag | None]:
        if quelle.startswith("domain:"):
            self._listen = self._listen.mit_fokus_domain(quelle.removeprefix("domain:"))
            return self._listen, None
        if quelle.startswith("prozess:"):
            self._listen = self._listen.mit_fokus_programm(quelle.removeprefix("prozess:"))
            return self._listen, None
        if quelle.startswith("seite:"):
            eintrag = GedaechtnisEintrag(self._aufgabe_key, "seite", quelle.removeprefix("seite:"), Status.FOKUS,
                                         "Von dir als passend markiert", 1.0, jetzt)
            self._gedaechtnis.merke(eintrag)
            return None, eintrag
        if quelle == QUELLE_HANDY:
            self.kamera.handy_aussetzen(jetzt + HANDY_KORREKTUR_PAUSE_S)
        elif quelle == QUELLE_STICHPROBE:
            self._stichprobe_zuruecksetzen(jetzt)
        return None, None
