"""Screenshots und JPEG-Verkleinerung für die KI."""

from __future__ import annotations

import sys
from typing import Callable

import cv2
import numpy as np

SCREENSHOT_KANTE = 1280


def verkleinere_jpeg(bild: np.ndarray, lange_kante: int, qualitaet: int = 80) -> bytes:
    if bild.ndim == 3 and bild.shape[2] == 4:
        bild = cv2.cvtColor(bild, cv2.COLOR_BGRA2BGR)
    hoehe, breite = bild.shape[:2]
    groesste = max(hoehe, breite)
    if groesste > lange_kante:
        faktor = lange_kante / groesste
        bild = cv2.resize(bild, (round(breite * faktor), round(hoehe * faktor)), interpolation=cv2.INTER_AREA)
    ok, daten = cv2.imencode(".jpg", bild, [cv2.IMWRITE_JPEG_QUALITY, qualitaet])
    if not ok:
        raise ValueError("JPEG-Kodierung fehlgeschlagen")
    return daten.tobytes()


class Bildschirm:
    """Bildquelle für den KI-Richter. Wird aus dem KI-Thread aufgerufen, daher pro Aufruf ein neues mss."""

    def __init__(self, kamera_jpeg: Callable[[], bytes | None]):
        self._kamera_jpeg = kamera_jpeg

    @staticmethod
    def _grab(sct, bereich: dict) -> bytes:
        return verkleinere_jpeg(np.asarray(sct.grab(bereich)), SCREENSHOT_KANTE)

    def alle_monitore(self) -> list[bytes]:
        import mss

        with mss.mss() as sct:
            return [self._grab(sct, m) for m in sct.monitors[1:]]

    def aktiver_monitor(self, fenster_id: int) -> bytes | None:
        import mss

        with mss.mss() as sct:
            bereich = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            if sys.platform == "win32":
                try:
                    import win32api
                    import win32con

                    monitor = win32api.MonitorFromWindow(fenster_id, win32con.MONITOR_DEFAULTTONEAREST)
                    links, oben, rechts, unten = win32api.GetMonitorInfo(monitor)["Monitor"]
                    bereich = {"left": links, "top": oben, "width": rechts - links, "height": unten - oben}
                except Exception:
                    pass
            return self._grab(sct, bereich)

    def webcam(self) -> bytes | None:
        return self._kamera_jpeg()
