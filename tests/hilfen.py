"""Gemeinsame Test-Helfer."""

from dataclasses import replace

from focusguard.config import Einstellungen
from focusguard.decision.rules import BROWSER_PROZESSE, domain_aus_url
from focusguard.models import PcBeobachtung


def pc(prozess="chrome.exe", titel="", url=None, zeit=0.0, fenster_id=1) -> PcBeobachtung:
    prozess = prozess.lower()
    return PcBeobachtung(zeit, fenster_id, prozess, titel, url, domain_aus_url(url), prozess in BROWSER_PROZESSE)


def einst(**abschnitte) -> Einstellungen:
    return replace(Einstellungen(), **abschnitte)
