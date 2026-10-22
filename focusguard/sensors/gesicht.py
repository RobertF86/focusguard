"""Gesichtserkennung und Kopfneigung mit dem MediaPipe FaceLandmarker."""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np


def pitch_aus_matrix(m: np.ndarray) -> float:
    """Neigung um die x-Achse in Grad; positiv = Kopf nach unten (MediaPipe-Kameraraum, y nach oben)."""
    r = np.asarray(m)[:3, :3]
    return math.degrees(math.atan2(r[2, 1], r[2, 2]))


class GesichtsAnalyse:
    def __init__(self, modell_pfad: Path):
        from mediapipe.tasks.python import BaseOptions, vision

        optionen = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(modell_pfad)),
            running_mode=vision.RunningMode.IMAGE,
            num_faces=1,
            output_facial_transformation_matrixes=True,
        )
        self._erkenner = vision.FaceLandmarker.create_from_options(optionen)

    def analysiere(self, bild_bgr: np.ndarray) -> tuple[bool, float | None]:
        import mediapipe as mp

        rgb = np.ascontiguousarray(cv2.cvtColor(bild_bgr, cv2.COLOR_BGR2RGB))
        ergebnis = self._erkenner.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        if not ergebnis.face_landmarks:
            return False, None
        if ergebnis.facial_transformation_matrixes:
            return True, pitch_aus_matrix(ergebnis.facial_transformation_matrixes[0])
        return True, None

    def schliesse(self) -> None:
        self._erkenner.close()
