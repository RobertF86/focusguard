"""Feste Regeln: Fokus- und Ablenkungs-Listen für Programme und Domains."""

from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urlsplit

from ..config import ListenEinst
from ..models import AufgabenListen, PcBeobachtung, Status, Urteil, quelle_domain, quelle_prozess

BROWSER_PROZESSE = frozenset({"chrome.exe", "msedge.exe", "brave.exe", "firefox.exe", "opera.exe", "vivaldi.exe"})

# Plattformen mit gemischtem Inhalt werden immer seitenweise beurteilt, nie als ganze Domain.
MISCH_PLATTFORMEN = frozenset({"youtube.com", "reddit.com", "x.com", "twitter.com", "google.com", "bing.com",
                               "duckduckgo.com"})


def domain_aus_url(url: str | None) -> str | None:
    if not url or not url.strip():
        return None
    url = url.strip()
    if "://" not in url:
        url = "http://" + url
    teile = urlsplit(url)
    if teile.scheme.lower() not in ("http", "https"):
        return None
    host = (teile.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def ist_misch_plattform(domain: str) -> bool:
    d = domain.lower()
    return domain_passt(d, MISCH_PLATTFORMEN) or re.search(r"(^|\.)google\.[a-z.]+$", d) is not None


def domain_passt(domain: str, liste: Iterable[str]) -> bool:
    return _passende_domain(domain, liste) is not None


def _passende_domain(domain: str | None, liste: Iterable[str]) -> str | None:
    if not domain:
        return None
    domain = domain.lower()
    for eintrag in liste:
        e = eintrag.lower()
        if domain == e or domain.endswith("." + e):
            return eintrag
    return None


def programm_passt(prozess: str, liste: Iterable[str]) -> bool:
    return _passendes_programm(prozess, liste) is not None


def _passendes_programm(prozess: str, liste: Iterable[str]) -> str | None:
    p = prozess.lower()
    for eintrag in liste:
        if eintrag.lower() == p:
            return eintrag
    return None


def regel_urteil(b: PcBeobachtung, aufgabe: AufgabenListen, global_listen: ListenEinst) -> Urteil | None:
    if (d := _passende_domain(b.domain, aufgabe.fokus_domains)) is not None:
        return Urteil(Status.FOKUS, quelle_domain(d), f"{d} gehört zur Aufgabe", "regel")
    if (d := _passende_domain(b.domain, (*aufgabe.ablenkung_domains, *global_listen.ablenkung_domains))) is not None:
        return Urteil(Status.ABGELENKT, quelle_domain(d), f"{d} steht auf der Ablenkungs-Liste", "regel")
    if (p := _passendes_programm(b.prozess, aufgabe.fokus_programme)) is not None:
        return Urteil(Status.FOKUS, quelle_prozess(p), f"{p} gehört zur Aufgabe", "regel")
    if (p := _passendes_programm(b.prozess, (*aufgabe.ablenkung_programme, *global_listen.ablenkung_programme))) is not None:
        return Urteil(Status.ABGELENKT, quelle_prozess(p), f"{p} steht auf der Ablenkungs-Liste", "regel")
    return None
