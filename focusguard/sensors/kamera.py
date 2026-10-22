"""Gemeinsame Kameraquelle und der Kamera-Sensor (Gesicht + Handy)."""

from __future__ import annotations

import math
import sys
import threading
from typing import Callable

import cv2
import numpy as np

from ..capture import verkleinere_jpeg
from ..clock import Uhr
from ..models import HandyBeobachtung, WebcamBeobachtung
from .handy import HANDY_SCHWELLE

KAMERA_NEUVERSUCH_S = 30.0
WEBCAM_KANTE = 640
KAMERA_PROBLEM = "Kamera nicht verfügbar"


def _standard_oeffnen(index: int):
    if sys.platform == "win32":
        return cv2.VideoCapture(index, cv2.CAP_DSHOW)
    return cv2.VideoCapture(index)


class Kamera:
    def __init__(self, index: int = 0, oeffnen: Callable[[int], object] | None = None):
        self._index = index
        self._oeffnen = oeffnen or _standard_oeffnen
        self._cap = None
        self._sperre = threading.Lock()
        self._letztes: np.ndarray | None = None

    def oeffne(self) -> bool:
        cap = self._oeffnen(self._index)
        if cap is None or not cap.isOpened():
            if cap is not None:
                cap.release()
            return False
        self._cap = cap
        return True

    def lies(self) -> np.ndarray | None:
        if self._cap is None:
            return None
        ok, bild = self._cap.read()
        if not ok or bild is None:
            return None
        with self._sperre:
            self._letztes = bild
        return bild

    def letztes_jpeg(self) -> bytes | None:
        with self._sperre:
            bild = self._letztes
        return None if bild is None else verkleinere_jpeg(bild, WEBCAM_KANTE)

    def schliesse(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        with self._sperre:
            self._letztes = None


class KameraSensor:
    def __init__(self, kamera, gesicht, handy, uhr: Uhr):
        self._kamera = kamera
        self._gesicht = gesicht
        self._handy = handy
        self._uhr = uhr
        self._offen = False
        self._letzter_versuch = -math.inf
        self._problem: str | None = None

    @property
    def problem(self) -> str | None:
        return self._problem

    def schritt(self) -> list[WebcamBeobachtung | HandyBeobachtung]:
        jetzt = self._uhr()
        if not self._offen:
            if jetzt - self._letzter_versuch < KAMERA_NEUVERSUCH_S:
                return []
            self._letzter_versuch = jetzt
            if not self._kamera.oeffne():
                self._problem = KAMERA_PROBLEM
                return []
            self._offen = True
            self._problem = None
        bild = self._kamera.lies()
        if bild is None:
            self._kamera.schliesse()
            self._offen = False
            self._letzter_versuch = jetzt
            self._problem = KAMERA_PROBLEM
            return []
        gesicht, pitch = self._gesicht.analysiere(bild)
        beobachtungen: list[WebcamBeobachtung | HandyBeobachtung] = [WebcamBeobachtung(jetzt, gesicht, pitch)]
        if self._handy is not None:
            score = self._handy.analysiere(bild)
            beobachtungen.append(HandyBeobachtung(jetzt, score >= HANDY_SCHWELLE, score))
        return beobachtungen

    def letztes_jpeg(self) -> bytes | None:
        return self._kamera.letztes_jpeg()

    def schliesse(self) -> None:
        self._kamera.schliesse()
        self._offen = False
        for analyse in (self._gesicht, self._handy):
            schliessen = getattr(analyse, "schliesse", None)
            if schliessen is not None:
                try:
                    schliessen()
                except Exception:
                    pass
