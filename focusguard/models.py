"""Gemeinsame Datenmodelle: Status, Beobachtungen, Urteile, KI-Anfragen, Aktionen, Session."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class Status(StrEnum):
    FOKUS = "fokus"
    UNKLAR = "unklar"
    ABGELENKT = "abgelenkt"
    ABWESEND = "abwesend"


@dataclass(frozen=True)
class PcBeobachtung:
    zeit: float
    fenster_id: int
    prozess: str
    fenstertitel: str
    url: str | None
    domain: str | None
    ist_browser: bool


@dataclass(frozen=True)
class WebcamBeobachtung:
    zeit: float
    gesicht: bool
    kopf_pitch_grad: float | None


@dataclass(frozen=True)
class HandyBeobachtung:
    zeit: float
    handy_erkannt: bool
    sicherheit: float


Beobachtung = PcBeobachtung | WebcamBeobachtung | HandyBeobachtung


@dataclass(frozen=True)
class Urteil:
    status: Status
    quelle: str
    begruendung: str
    herkunft: str  # "regel", "gedaechtnis", "ki", "lokal"
    seit: float | None = None


def _ohne_duplikate(werte: tuple[str, ...], neu: str) -> tuple[str, ...]:
    return werte if neu in werte else (*werte, neu)


@dataclass(frozen=True)
class AufgabenListen:
    fokus_programme: tuple[str, ...] = ()
    fokus_domains: tuple[str, ...] = ()
    ablenkung_programme: tuple[str, ...] = ()
    ablenkung_domains: tuple[str, ...] = ()

    def mit_fokus_domain(self, d: str) -> AufgabenListen:
        return AufgabenListen(self.fokus_programme, _ohne_duplikate(self.fokus_domains, d),
                              self.ablenkung_programme, self.ablenkung_domains)

    def mit_fokus_programm(self, p: str) -> AufgabenListen:
        return AufgabenListen(_ohne_duplikate(self.fokus_programme, p), self.fokus_domains,
                              self.ablenkung_programme, self.ablenkung_domains)

    def ist_leer(self) -> bool:
        return not (self.fokus_programme or self.fokus_domains
                    or self.ablenkung_programme or self.ablenkung_domains)


@dataclass(frozen=True)
class GedaechtnisEintrag:
    aufgabe_key: str
    ebene: str  # "seite", "domain", "programm"
    schluessel: str
    status: Status
    begruendung: str
    sicherheit: float
    zeit: float


class KiArt(StrEnum):
    SEITE = "seite"
    HANDY = "handy"
    STICHPROBE = "stichprobe"


_PRIORITAET = {KiArt.HANDY: 0, KiArt.SEITE: 1, KiArt.STICHPROBE: 2}


@dataclass(frozen=True)
class KiAnfrage:
    art: KiArt
    quelle: str
    zeit: float
    pc: PcBeobachtung | None
    mit_bildschirm: bool
    mit_webcam: bool

    @property
    def prioritaet(self) -> int:
        return _PRIORITAET[self.art]


@dataclass(frozen=True)
class KiUrteil:
    status: Status
    begruendung: str
    sicherheit: float
    gilt_fuer: str  # "seite", "domain", "programm"


@dataclass(frozen=True)
class KiErgebnis:
    anfrage: KiAnfrage
    urteil: KiUrteil | None
    fehler: str | None
    tokens_ein: int = 0
    tokens_aus: int = 0


# Aktionen der Eskalation an UI und Blocker

@dataclass(frozen=True)
class Hinweis:
    text: str


@dataclass(frozen=True)
class OverlayZeigen:
    text: str
    quelle: str


@dataclass(frozen=True)
class OverlaySchliessen:
    pass


@dataclass(frozen=True)
class Sperren:
    quelle: str


@dataclass(frozen=True)
class HandyOverlay:
    pass


@dataclass(frozen=True)
class Begruessung:
    minuten_weg: int


@dataclass(frozen=True)
class IconStatus:
    farbe: str  # "grau", "gruen", "gelb", "rot", "blau"


Aktion = Hinweis | OverlayZeigen | OverlaySchliessen | Sperren | HandyOverlay | Begruessung | IconStatus


@dataclass
class Session:
    id: int | None
    aufgabe: str
    aufgabe_key: str
    start: float
    geplant_min: int
    ende: float | None = None
    vorzeitig_beendet: bool = False


@dataclass(frozen=True)
class Ereignis:
    zeit: float
    art: str
    quelle: str
    status: str
    details: dict = field(default_factory=dict)


QUELLE_HANDY = "handy"
QUELLE_STICHPROBE = "stichprobe"


def aufgabe_key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def quelle_domain(d: str) -> str:
    return f"domain:{d}"


def quelle_prozess(p: str) -> str:
    return f"prozess:{p}"


def quelle_seite(schluessel: str) -> str:
    return f"seite:{schluessel}"
