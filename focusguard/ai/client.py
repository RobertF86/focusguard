"""KI-Richter: Warteschlange mit Vorrang, Ratenbegrenzung und Anbindung an die Claude-API."""

from __future__ import annotations

import itertools
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from ..clock import Uhr
from ..decision.memory import seiten_schluessel
from ..models import AufgabenListen, KiAnfrage, KiArt, KiErgebnis, PcBeobachtung
from .prompts import (STARTLISTEN_SCHEMA, SYSTEM_STARTLISTEN, SYSTEM_URTEIL, URTEIL_SCHEMA, KiAntwortFehler,
                      baue_anfrage, handy_inhalt, parse_startlisten, parse_urteil, seite_inhalt,
                      startlisten_inhalt, stichprobe_inhalt)


class KiFehler(Exception):
    pass


@dataclass(frozen=True)
class KiRohAntwort:
    text: str
    tokens_ein: int
    tokens_aus: int


Sender = Callable[[dict], KiRohAntwort]


def anthropic_sender(client=None, timeout_s: float = 15.0) -> Sender:
    import anthropic

    if client is None:
        client = anthropic.Anthropic(timeout=timeout_s, max_retries=0)

    def senden(kwargs: dict) -> KiRohAntwort:
        try:
            antwort = client.messages.create(**kwargs)
        except anthropic.APIError as e:
            raise KiFehler(f"KI nicht erreichbar: {e}") from e
        stop = getattr(antwort, "stop_reason", None)
        if stop == "refusal":
            raise KiFehler("KI hat die Anfrage abgelehnt")
        if stop == "max_tokens":
            raise KiFehler("KI-Antwort wurde abgeschnitten")
        text = next((b.text for b in antwort.content if getattr(b, "type", None) == "text"), None)
        if text is None:
            raise KiFehler("KI-Antwort enthält keinen Text")
        usage = getattr(antwort, "usage", None)
        return KiRohAntwort(text, getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0)

    return senden


class BildquellePort(Protocol):
    def aktiver_monitor(self, fenster_id: int) -> bytes | None: ...
    def alle_monitore(self) -> list[bytes]: ...
    def webcam(self) -> bytes | None: ...


class Ratenbegrenzer:
    def __init__(self, pro_minute: int, uhr: Uhr):
        self._pro_minute = pro_minute
        self._uhr = uhr
        self._marken = float(pro_minute)
        self._zuletzt = uhr()

    def versuche(self) -> bool:
        jetzt = self._uhr()
        self._marken = min(float(self._pro_minute),
                           self._marken + (jetzt - self._zuletzt) * self._pro_minute / 60.0)
        self._zuletzt = jetzt
        if self._marken >= 1.0:
            self._marken -= 1.0
            return True
        return False


def _sicher(funktion, ersatz):
    try:
        return funktion()
    except Exception:
        return ersatz


class KiRichter:
    def __init__(self, sender: Sender, bilder: BildquellePort, modell: str, min_sicherheit: float,
                 pro_minute: int, uhr: Uhr, ablage: Path | None = None,
                 aktuelle_pc: Callable[[], PcBeobachtung | None] | None = None):
        self._sender = sender
        self._bilder = bilder
        self._modell = modell
        self._min_sicherheit = min_sicherheit
        self._begrenzer = Ratenbegrenzer(pro_minute, uhr)
        self._uhr = uhr
        self._ablage = ablage
        self._aktuelle_pc = aktuelle_pc
        self._bildschirm_pause = False
        self._sperre = threading.Lock()
        self._schlange: list[tuple[int, KiAnfrage, str]] = []
        self._zaehler = itertools.count()

    def einreihen(self, anfrage: KiAnfrage, aufgabe: str) -> None:
        with self._sperre:
            if any(a.quelle == anfrage.quelle for _, a, _ in self._schlange):
                return
            self._schlange.append((next(self._zaehler), anfrage, aufgabe))

    def leeren(self) -> None:
        with self._sperre:
            self._schlange.clear()

    def setze_bildschirm_pause(self, an: bool) -> None:
        """Solange ein Overlay offen ist, würden Screenshots nur das Overlay zeigen: solche Anfragen warten."""
        with self._sperre:
            self._bildschirm_pause = an

    @staticmethod
    def _braucht_bildschirm(a: KiAnfrage) -> bool:
        return a.art is KiArt.SEITE or (a.art is KiArt.STICHPROBE and a.mit_bildschirm)

    def _seite_veraltet(self, a: KiAnfrage) -> bool:
        if a.art is not KiArt.SEITE or self._aktuelle_pc is None:
            return False
        jetzt_pc = _sicher(self._aktuelle_pc, None)
        return jetzt_pc is None or seiten_schluessel(jetzt_pc) != seiten_schluessel(a.pc)

    def verarbeite_naechste(self) -> KiErgebnis | None:
        with self._sperre:
            moeglich = [e for e in self._schlange
                        if not (self._bildschirm_pause and self._braucht_bildschirm(e[1]))]
            if not moeglich:
                return None
            eintrag = min(moeglich, key=lambda e: (e[1].prioritaet, e[0]))
            if self._seite_veraltet(eintrag[1]):
                # Screenshot und Titel würden nicht mehr zusammenpassen; die Seite wird bei Bedarf neu angefragt.
                self._schlange.remove(eintrag)
                return KiErgebnis(eintrag[1], None, "Seite nicht mehr aktiv")
            if not self._begrenzer.versuche():
                return None
            self._schlange.remove(eintrag)
        _, anfrage, aufgabe = eintrag
        return self._sende(anfrage, aufgabe)

    def _inhalt(self, a: KiAnfrage, aufgabe: str) -> tuple[list[dict] | None, list[bytes], str | None]:
        if a.art is KiArt.SEITE:
            bild = _sicher(lambda: self._bilder.aktiver_monitor(a.pc.fenster_id), None)
            return seite_inhalt(aufgabe, a.pc, bild), [bild] if bild else [], None
        if a.art is KiArt.HANDY:
            cam = _sicher(self._bilder.webcam, None)
            if not cam:
                return None, [], "Kein Webcam-Bild"
            return handy_inhalt(aufgabe, cam), [cam], None
        monitore = _sicher(self._bilder.alle_monitore, []) if a.mit_bildschirm else []
        cam = _sicher(self._bilder.webcam, None) if a.mit_webcam else None
        if not monitore and not cam and a.pc is None:
            return None, [], "Keine Bilder für die Stichprobe"
        bilder = [*monitore, *([cam] if cam else [])]
        return stichprobe_inhalt(aufgabe, a.pc, monitore, cam), bilder, None

    def _sende(self, a: KiAnfrage, aufgabe: str) -> KiErgebnis:
        inhalt, bilder, fehler = self._inhalt(a, aufgabe)
        if inhalt is None:
            return KiErgebnis(a, None, fehler)
        kwargs = baue_anfrage(self._modell, SYSTEM_URTEIL, inhalt, URTEIL_SCHEMA)
        try:
            roh = self._sender(kwargs)
        except Exception as e:
            ergebnis = KiErgebnis(a, None, str(e))
        else:
            try:
                urteil = parse_urteil(roh.text, self._min_sicherheit)
                ergebnis = KiErgebnis(a, urteil, None, roh.tokens_ein, roh.tokens_aus)
            except KiAntwortFehler as e:
                ergebnis = KiErgebnis(a, None, str(e), roh.tokens_ein, roh.tokens_aus)
        if self._ablage is not None:
            self._ablegen(ergebnis, bilder)
        return ergebnis

    def _ablegen(self, e: KiErgebnis, bilder: list[bytes]) -> None:
        try:
            self._ablage.mkdir(parents=True, exist_ok=True)
            praefix = f"{int(self._uhr() * 1000)}_{e.anfrage.art.value}"
            for n, bild in enumerate(bilder, start=1):
                (self._ablage / f"{praefix}_{n}.jpg").write_bytes(bild)
            inhalt = {"quelle": e.anfrage.quelle}
            if e.urteil is not None:
                inhalt["urteil"] = {"status": e.urteil.status.value, "begruendung": e.urteil.begruendung,
                                    "sicherheit": e.urteil.sicherheit, "gilt_fuer": e.urteil.gilt_fuer}
            else:
                inhalt["fehler"] = e.fehler
            (self._ablage / f"{praefix}.json").write_text(json.dumps(inhalt, ensure_ascii=False, indent=2),
                                                          encoding="utf-8")
        except OSError:
            pass

    def startlisten(self, aufgabe: str) -> AufgabenListen | None:
        kwargs = baue_anfrage(self._modell, SYSTEM_STARTLISTEN, startlisten_inhalt(aufgabe), STARTLISTEN_SCHEMA)
        try:
            return parse_startlisten(self._sender(kwargs).text)
        except Exception:
            return None
