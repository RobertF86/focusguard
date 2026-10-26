"""Gedächtnis der KI-Urteile pro Seite oder Domain.

Ganze Programme legen nur die Listen fest. Ein KI-Urteil über ein Programm gilt pro Fenstertitel und nur
PROGRAMM_GUELTIG_S lang: In Programmen wie Claude oder dem Explorer bleibt der Titel gleich, der Inhalt nicht.
Sicherheit 1.0 haben nur deine eigenen Korrekturen; sie laufen nie ab.
"""

from __future__ import annotations

from typing import Iterable

from .rules import ist_misch_plattform
from ..models import (GedaechtnisEintrag, KiUrteil, PcBeobachtung, Status, quelle_domain, quelle_prozess,
                      quelle_seite)

PROGRAMM_GUELTIG_S = 15 * 60
KI_HOECHSTE_SICHERHEIT = 0.99


def seiten_schluessel(b: PcBeobachtung) -> str:
    return f"{b.domain or b.prozess}|{b.fenstertitel}"


def eintrag_fuer(b: PcBeobachtung, u: KiUrteil, aufgabe_key: str, zeit: float) -> GedaechtnisEintrag | None:
    if u.status is Status.UNKLAR:
        return None
    if u.gilt_fuer == "domain" and b.domain and not ist_misch_plattform(b.domain):
        ebene, schluessel = "domain", b.domain
    else:
        ebene, schluessel = "seite", seiten_schluessel(b)
    return GedaechtnisEintrag(aufgabe_key, ebene, schluessel, u.status, u.begruendung,
                              min(u.sicherheit, KI_HOECHSTE_SICHERHEIT), zeit)


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

    def suche(self, b: PcBeobachtung, jetzt: float) -> GedaechtnisEintrag | None:
        seite = self._eintraege.get(("seite", seiten_schluessel(b)))
        if seite is not None and not b.ist_browser and seite.sicherheit < 1.0 \
                and jetzt - seite.zeit > PROGRAMM_GUELTIG_S:
            seite = None                                       # altes KI-Urteil über ein Programm: neu fragen
        if seite is not None:
            return seite
        return self._eintraege.get(("domain", b.domain)) if b.domain else None
