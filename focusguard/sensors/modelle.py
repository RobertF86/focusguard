"""Download der MediaPipe-Modelle in den Datenordner."""

from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path
from typing import Callable

GESICHT_MODELL = ("face_landmarker.task",
                  "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/"
                  "face_landmarker.task")
OBJEKT_MODELL = ("efficientdet_lite0.tflite",
                 "https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/float16/1/"
                 "efficientdet_lite0.tflite")


class ModellFehler(Exception):
    pass


DOWNLOAD_TIMEOUT_S = 30


def _herunterladen(url: str, ziel: Path) -> None:
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_S) as antwort, open(ziel, "wb") as datei:
        shutil.copyfileobj(antwort, datei)


def stelle_modell_bereit(dateiname: str, url: str, ordner: Path,
                         herunterladen: Callable[[str, Path], None] | None = None) -> Path:
    ordner = Path(ordner)
    ziel = ordner / dateiname
    if ziel.exists() and ziel.stat().st_size > 0:
        return ziel
    herunterladen = herunterladen or _herunterladen
    teil = ziel.with_name(ziel.name + ".part")
    try:
        ordner.mkdir(parents=True, exist_ok=True)
        herunterladen(url, teil)
        teil.replace(ziel)
    except Exception as e:
        raise ModellFehler(f"Modell {dateiname} konnte nicht geladen werden: {e}") from e
    return ziel
