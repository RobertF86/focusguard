"""Gedächtnis der KI-Urteile pro Seite, Domain oder Programm."""

from __future__ import annotations

from typing import Iterable

from .rules import ist_misch_plattform
from ..models import (GedaechtnisEintrag, KiUrteil, PcBeobachtung, Status, quelle_domain, quelle_prozess,
                      quelle_seite)


def seiten_schluessel(b: PcBeobachtung) -> str:
    return f"{b.domain or b.prozess}|{b.fenstertitel}"


def eintrag_fuer(b: PcBeobachtung, u: KiUrteil, aufgabe_key: str, zeit: float) -> GedaechtnisEintrag | None:
    if u.status is Status.UNKLAR:
        return None
    ebene = u.gilt_fuer
    if ebene == "domain" and (not b.domain or ist_misch_plattform(b.domain)):
        ebene = "seite"
    if ebene == "programm" and b.ist_browser:
        ebene = "seite"
    if ebene == "domain":
        schluessel = b.domain
    elif ebene == "programm":
        schluessel = b.prozess
    else:
        ebene, schluessel = "seite", seiten_schluessel(b)
    return GedaechtnisEintrag(aufgabe_key, ebene, schluessel, u.status, u.begruendung, u.sicherheit, zeit)


def quelle_fuer(e: GedaechtnisEintrag) -> str:
    if e.ebene == "domain":
        return quelle_domain(e.schluessel)
    if e.ebene == "programm":
        return quelle_prozess(e.schluessel)
    return quelle_seite(e.schluessel)


class Gedaechtnis:
    def __init__(self, eintraege: Iterable[GedaechtnisEintrag] = ()):
        self._eintraege: dict[tuple[str, str], GedaechtnisEintrag] = {}
        for e in eintraege:
            self.merke(e)

    def merke(self, e: GedaechtnisEintrag) -> None:
        self._eintraege[(e.ebene, e.schluessel)] = e

    def suche(self, b: PcBeobachtung) -> GedaechtnisEintrag | None:
        kandidaten = [("seite", seiten_schluessel(b))]
        if b.domain:
            kandidaten.append(("domain", b.domain))
        if not b.ist_browser:
            kandidaten.append(("programm", b.prozess))
        for k in kandidaten:
            if k in self._eintraege:
                return self._eintraege[k]
        return None
