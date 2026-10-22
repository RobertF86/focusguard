"""Regeln für Webcam und Smartphone: Abwesenheit und Handy-Nutzung."""

from __future__ import annotations

import math
from statistics import median

from ..config import ErkennungEinst
from ..models import QUELLE_HANDY, HandyBeobachtung, KiUrteil, Status, Urteil, WebcamBeobachtung

HANDY_LUECKE_S = 1.0          # so lange darf die Handy-Erkennung aussetzen, ohne den Lauf zu unterbrechen
WEBCAM_VERALTET_S = 3.0       # ohne neue Bilder gilt die Webcam als stumm
GESICHT_AKTUELL_S = 1.0       # Handy-Regeln nur, wenn eben noch ein Gesicht zu sehen war
BASELINE_ANZAHL = 20
KI_FEHLER_PAUSE_S = 30.0


class KameraBewerter:
    def __init__(self, erkennung: ErkennungEinst, handy_pruefung_sekunden: int, start: float,
                 webcam_aktiv: bool, smartphone_aktiv: bool):
        self._e = erkennung
        self._pruef_s = handy_pruefung_sekunden
        self._webcam_aktiv = webcam_aktiv
        self._smartphone_aktiv = smartphone_aktiv

        self._letzte_webcam: float | None = None
        self._letztes_gesicht = start                 # Abwesenheit zählt ab Session-Start
        self._letztes_echtes_gesicht: float | None = None
        self._baseline_werte: list[float] = []
        self._gesenkt_seit: float | None = None

        self._handy_lauf_start: float | None = None
        self._letztes_handy: float | None = None
        self._ausgesetzt_bis = -math.inf

        self._ki_urteil: KiUrteil | None = None
        self._ki_zeit = -math.inf
        self._naechste_anfrage = -math.inf

    def setze_aktiv(self, webcam: bool, smartphone: bool) -> None:
        self._webcam_aktiv = webcam
        self._smartphone_aktiv = smartphone

    def _baseline(self) -> float:
        return median(self._baseline_werte) if len(self._baseline_werte) >= BASELINE_ANZAHL else 0.0

    def webcam(self, b: WebcamBeobachtung) -> None:
        self._letzte_webcam = b.zeit
        if not b.gesicht:
            self._gesenkt_seit = None
            return
        self._letztes_gesicht = b.zeit
        self._letztes_echtes_gesicht = b.zeit
        if b.kopf_pitch_grad is None:
            self._gesenkt_seit = None
            return
        if len(self._baseline_werte) < BASELINE_ANZAHL:
            self._baseline_werte.append(b.kopf_pitch_grad)
        if b.kopf_pitch_grad - self._baseline() > self._e.kopf_gesenkt_grad:
            if self._gesenkt_seit is None:
                self._gesenkt_seit = b.zeit
        else:
            self._gesenkt_seit = None

    def handy(self, b: HandyBeobachtung) -> None:
        if not b.handy_erkannt:
            return
        if self._letztes_handy is None or b.zeit - self._letztes_handy > HANDY_LUECKE_S:
            self._handy_lauf_start = b.zeit
        self._letztes_handy = b.zeit

    def _handy_aktiv(self, jetzt: float) -> bool:
        return (self._smartphone_aktiv
                and jetzt >= self._ausgesetzt_bis
                and self._letztes_echtes_gesicht is not None
                and jetzt - self._letztes_echtes_gesicht <= GESICHT_AKTUELL_S
                and self._letztes_handy is not None
                and jetzt - self._letztes_handy <= HANDY_LUECKE_S
                and self._handy_lauf_start is not None
                and jetzt - self._handy_lauf_start >= self._e.handy_mindestdauer_sekunden)

    def _kopf_lange_gesenkt(self, jetzt: float) -> bool:
        return self._gesenkt_seit is not None and jetzt - self._gesenkt_seit >= self._e.handy_mindestdauer_sekunden

    def _gueltiges_ki_urteil(self, jetzt: float) -> KiUrteil | None:
        if self._ki_urteil is not None and jetzt - self._ki_zeit <= self._pruef_s:
            return self._ki_urteil
        return None

    def urteil(self, jetzt: float) -> Urteil | None:
        handy_unklar = None
        if self._handy_aktiv(jetzt):
            if self._kopf_lange_gesenkt(jetzt):
                return Urteil(Status.ABGELENKT, QUELLE_HANDY, "Handy in der Hand", "lokal")
            ki = self._gueltiges_ki_urteil(jetzt)
            if ki is not None and ki.status is Status.ABGELENKT:
                return Urteil(Status.ABGELENKT, QUELLE_HANDY, ki.begruendung, "ki")
            if ki is None or ki.status is not Status.FOKUS:
                handy_unklar = Urteil(Status.UNKLAR, QUELLE_HANDY, "Handy im Bild", "lokal")

        if (self._webcam_aktiv and self._letzte_webcam is not None
                and jetzt - self._letzte_webcam <= WEBCAM_VERALTET_S
                and jetzt - self._letztes_gesicht > self._e.abwesend_nach_sekunden):
            return Urteil(Status.ABWESEND, "", "Niemand am Platz", "lokal")
        return handy_unklar

    def braucht_ki(self, jetzt: float) -> bool:
        return (self._handy_aktiv(jetzt)
                and not self._kopf_lange_gesenkt(jetzt)
                and self._gueltiges_ki_urteil(jetzt) is None
                and jetzt >= self._naechste_anfrage)

    def ki_angefragt(self, jetzt: float) -> None:
        self._naechste_anfrage = jetzt + self._pruef_s

    def ki_ergebnis(self, u: KiUrteil | None, jetzt: float) -> None:
        if u is None:
            self._naechste_anfrage = jetzt + KI_FEHLER_PAUSE_S
            return
        self._ki_urteil = u
        self._ki_zeit = jetzt

    def handy_aussetzen(self, bis: float) -> None:
        self._ausgesetzt_bis = bis

    def handy_frei_seit(self, jetzt: float) -> float:
        if self._letztes_handy is None:
            return math.inf
        return jetzt - self._letztes_handy
