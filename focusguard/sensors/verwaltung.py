"""Startet und stoppt die Sensor-Threads passend zu den Checkboxen."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

from .base import SensorThread

PC_INTERVALL_S = 1.0
KAMERA_INTERVALL_S = 0.5
JOIN_TIMEOUT_S = 2.0


class SensorVerwaltung:
    def __init__(self, ausgabe: Callable[[object], None], fehler: Callable[[str, str], None],
                 pc_fabrik: Callable[[], Callable[[], list]], kamera_fabrik: Callable[[bool], object],
                 thread_fabrik=SensorThread):
        self._ausgabe = ausgabe
        self._fehler = fehler
        self._pc_fabrik = pc_fabrik
        self._kamera_fabrik = kamera_fabrik
        self._thread_fabrik = thread_fabrik
        self._pc_thread = None
        self._kamera_thread = None
        self._kamera_sensor = None
        self._kamera_smartphone: bool | None = None
        self._startproblem: str | None = None

    def setze(self, pc: bool, webcam: bool, smartphone: bool) -> None:
        if pc and self._pc_thread is None:
            try:
                schritt = self._pc_fabrik()
            except Exception as e:
                self._fehler("pc", f"PC-Sensor konnte nicht starten: {e!r}")
            else:
                self._pc_thread = self._thread_fabrik("pc", schritt, PC_INTERVALL_S, self._ausgabe, self._fehler)
                self._pc_thread.start()
        elif not pc and self._pc_thread is not None:
            self._stoppe_thread(self._pc_thread)
            self._pc_thread = None

        kamera_noetig = webcam or smartphone
        if self._kamera_thread is not None and (not kamera_noetig or self._kamera_smartphone != smartphone):
            self._stoppe_kamera()
        if kamera_noetig and self._kamera_thread is None:
            try:
                sensor = self._kamera_fabrik(smartphone)
            except Exception as e:
                self._startproblem = "Kamera-Sensor konnte nicht starten"
                self._fehler("kamera", f"{self._startproblem}: {e!r}")
                return
            self._startproblem = None
            self._kamera_sensor = sensor
            self._kamera_smartphone = smartphone
            self._kamera_thread = self._thread_fabrik("kamera", sensor.schritt, KAMERA_INTERVALL_S, self._ausgabe,
                                                      self._fehler, beim_stopp=sensor.schliesse)
            self._kamera_thread.start()
        elif not kamera_noetig:
            self._startproblem = None

    @staticmethod
    def _stoppe_thread(thread) -> None:
        thread.stoppe()
        thread.join(JOIN_TIMEOUT_S)

    def _stoppe_kamera(self) -> None:
        if self._kamera_thread is not None:
            self._stoppe_thread(self._kamera_thread)
        self._kamera_thread = None
        self._kamera_sensor = None
        self._kamera_smartphone = None

    def stoppe(self) -> None:
        if self._pc_thread is not None:
            self._stoppe_thread(self._pc_thread)
            self._pc_thread = None
        self._stoppe_kamera()
        self._startproblem = None

    def problem(self) -> str | None:
        if self._startproblem:
            return self._startproblem
        sensor = self._kamera_sensor
        return sensor.problem if sensor is not None else None

    def kamera_jpeg(self) -> bytes | None:
        sensor = self._kamera_sensor
        if sensor is None:
            return None
        try:
            return sensor.letztes_jpeg()
        except Exception:
            return None


def standard_verwaltung(ausgabe: Callable[[object], None], fehler: Callable[[str, str], None],
                        datenordner: Path) -> SensorVerwaltung:
    from .gesicht import GesichtsAnalyse
    from .handy import HandyErkennung
    from .kamera import Kamera, KameraSensor
    from .modelle import GESICHT_MODELL, OBJEKT_MODELL, stelle_modell_bereit
    from .pc import PcSensor, windows_url, windows_vordergrund

    modelle = Path(datenordner) / "modelle"

    def pc_fabrik():
        return PcSensor(windows_vordergrund, windows_url, time.time, os.getpid()).schritt

    def kamera_fabrik(smartphone: bool):
        gesicht = GesichtsAnalyse(stelle_modell_bereit(*GESICHT_MODELL, modelle))
        handy = HandyErkennung(stelle_modell_bereit(*OBJEKT_MODELL, modelle)) if smartphone else None
        return KameraSensor(Kamera(), gesicht, handy, time.time)

    return SensorVerwaltung(ausgabe, fehler, pc_fabrik, kamera_fabrik)
