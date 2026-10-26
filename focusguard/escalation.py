"""Eskalation in Stufen: Hinweis → Overlay → Sperre, mit Rückfall-Gedächtnis und Begrüßung nach Abwesenheit."""

from __future__ import annotations

import math

from .config import EskalationEinst
from .models import (QUELLE_HANDY, QUELLE_STICHPROBE, Aktion, Begruessung, HandyOverlay, Hinweis, IconStatus,
                     OverlaySchliessen, OverlayZeigen, Sperren, Status, Urteil)

HANDY_FREI_S = 5.0          # so lange ohne Handy, bis das Handy-Overlay verschwindet
OVERLAY_PAUSE_S = 5.0       # nach „Zurück zur Aufgabe“ erscheint das Overlay frühestens so spät wieder


class Eskalation:
    def __init__(self, e: EskalationEinst, begruessung_ab_minuten: int, start: float):
        self._e = e
        self._begruessung_ab_s = begruessung_ab_minuten * 60
        self._icon = "gruen"
        self._lauf_start: float | None = None
        self._stufe = 0
        self._bonus = 0
        self._letztes_ende: float | None = None
        self._fokus_seit: float | None = start
        self._overlay_offen = False
        self._overlay_gezeigt = False          # im laufenden Ablenkungs-Lauf schon ein Overlay gezeigt
        self._overlay_pause_bis = -math.inf
        self._gesperrt_im_lauf: set[str] = set()
        self._handy_overlay = False
        self._letzte_ablenkung = -math.inf
        self._abwesend_seit: float | None = None

    @property
    def stufe(self) -> int:
        return self._stufe

    def schritt(self, u: Urteil, jetzt: float) -> list[Aktion]:
        aktionen: list[Aktion] = []
        if u.status is Status.ABWESEND:
            if self._abwesend_seit is None:
                self._abwesend_seit = jetzt
        elif self._abwesend_seit is not None:
            dauer = jetzt - self._abwesend_seit
            if dauer >= self._begruessung_ab_s:
                aktionen.append(Begruessung(int(dauer // 60)))
            self._abwesend_seit = None

        if u.status is Status.ABGELENKT:
            aktionen += self._abgelenkt(u, jetzt)
        else:
            aktionen += self._nicht_abgelenkt(u, jetzt)

        farbe = self._farbe(u)
        if farbe != self._icon:
            self._icon = farbe
            aktionen.append(IconStatus(farbe))
        return aktionen

    def _abgelenkt(self, u: Urteil, jetzt: float) -> list[Aktion]:
        aktionen: list[Aktion] = []
        self._letzte_ablenkung = jetzt
        self._fokus_seit = None
        if self._lauf_start is None:
            start = min(jetzt, u.seit) if u.seit is not None else jetzt
            self._lauf_start = start
            rueckfall = (self._letztes_ende is not None
                         and start - self._letztes_ende <= self._e.rueckfall_fenster_minuten * 60)
            self._bonus = 1 if rueckfall else 0
            self._stufe = 0
            self._gesperrt_im_lauf = set()
            self._handy_overlay = False
            self._overlay_gezeigt = False

        dauer = jetzt - self._lauf_start
        ziel = 0
        if dauer >= self._e.stufe3_sekunden:
            ziel = 3
        elif dauer >= self._e.stufe2_sekunden:
            ziel = 2
        elif dauer >= self._e.stufe1_sekunden:
            ziel = 1
        if ziel > 0:
            ziel = min(3, ziel + self._bonus)
        if u.quelle == QUELLE_STICHPROBE:
            ziel = min(ziel, 2)

        if ziel > self._stufe:
            self._stufe = ziel
            aktionen += self._stufen_aktion(ziel, u)
        elif self._stufe == 3:
            if u.quelle == QUELLE_HANDY and not self._handy_overlay:
                aktionen += self._stufen_aktion(3, u)
            elif u.quelle not in (QUELLE_HANDY, QUELLE_STICHPROBE) and u.quelle not in self._gesperrt_im_lauf:
                aktionen += self._stufen_aktion(3, u)

        if self._stufe >= 2 and not self._overlay_offen and jetzt >= self._overlay_pause_bis:
            self._overlay_offen = True
            erneut, self._overlay_gezeigt = self._overlay_gezeigt, True
            aktionen.append(HandyOverlay(erneut) if self._handy_overlay
                            else OverlayZeigen(u.begruendung, u.quelle, erneut))
        return aktionen

    def _stufen_aktion(self, stufe: int, u: Urteil) -> list[Aktion]:
        if stufe == 1:
            return [Hinweis(u.begruendung)]
        if stufe == 2:
            self._overlay_offen = self._overlay_gezeigt = True
            return [OverlayZeigen(u.begruendung, u.quelle)]
        if u.quelle == QUELLE_HANDY:
            self._handy_overlay = True
            self._overlay_offen = self._overlay_gezeigt = True
            return [HandyOverlay()]
        self._gesperrt_im_lauf.add(u.quelle)
        return [Sperren(u.quelle)]

    def _nicht_abgelenkt(self, u: Urteil, jetzt: float) -> list[Aktion]:
        aktionen: list[Aktion] = []
        if self._lauf_start is not None:
            if not (self._handy_overlay and jetzt - self._letzte_ablenkung < HANDY_FREI_S):
                aktionen += self._lauf_beenden()
                self._letztes_ende = jetzt
        if u.status in (Status.FOKUS, Status.UNKLAR):
            if self._fokus_seit is None:
                self._fokus_seit = jetzt
            elif jetzt - self._fokus_seit >= self._e.reset_nach_fokus_minuten * 60:
                self._letztes_ende = None
        else:
            self._fokus_seit = None
        return aktionen

    def _lauf_beenden(self) -> list[Aktion]:
        aktionen: list[Aktion] = []
        if self._overlay_offen:
            aktionen.append(OverlaySchliessen())
            self._overlay_offen = False
        self._lauf_start = None
        self._stufe = 0
        self._handy_overlay = False
        return aktionen

    def _farbe(self, u: Urteil) -> str:
        if u.status is Status.ABWESEND and self._lauf_start is None:
            return "blau"
        return {0: "gruen", 1: "gelb"}.get(self._stufe, "rot")

    def zurueck_zur_aufgabe(self, jetzt: float) -> list[Aktion]:
        self._overlay_pause_bis = jetzt + OVERLAY_PAUSE_S
        if self._overlay_offen:
            self._overlay_offen = False
            return [OverlaySchliessen()]
        return []

    def korrektur(self, jetzt: float) -> list[Aktion]:
        aktionen = self._lauf_beenden()
        if self._icon != "gruen":
            self._icon = "gruen"
            aktionen.append(IconStatus("gruen"))
        return aktionen
