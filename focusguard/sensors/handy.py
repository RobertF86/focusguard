"""Handy-Erkennung mit dem MediaPipe ObjectDetector (EfficientDet-Lite0, COCO-Klasse „cell phone“)."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import cv2
import numpy as np

HANDY_KATEGORIE = "cell phone"
HANDY_SCHWELLE = 0.5


def handy_score(erkennungen: Iterable[tuple[str, float]]) -> float:
    return max((score for kategorie, score in erkennungen if kategorie == HANDY_KATEGORIE), default=0.0)


class HandyErkennung:
    def __init__(self, modell_pfad: Path):
        from mediapipe.tasks.python import BaseOptions, vision

        optionen = vision.ObjectDetectorOptions(
            base_options=BaseOptions(model_asset_path=str(modell_pfad)),
            running_mode=vision.RunningMode.IMAGE,
            score_threshold=0.3,
            category_allowlist=[HANDY_KATEGORIE],
        )
        self._erkenner = vision.ObjectDetector.create_from_options(optionen)

    def analysiere(self, bild_bgr: np.ndarray) -> float:
        import mediapipe as mp

        rgb = np.ascontiguousarray(cv2.cvtColor(bild_bgr, cv2.COLOR_BGR2RGB))
        ergebnis = self._erkenner.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        return handy_score((k.category_name, k.score) for d in ergebnis.detections for k in d.categories)

    def schliesse(self) -> None:
        self._erkenner.close()
