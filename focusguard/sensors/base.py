"""Sensor-Thread mit Neustart nach Absturz."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable

from ..clock import Uhr

AUFGEGEBEN = "Sensor dauerhaft ausgeschaltet"


class AbsturzZaehler:
    def __init__(self, max_abstuerze: int = 3, fenster_s: float = 300.0):
        self._max = max_abstuerze
        self._fenster_s = fenster_s
        self._zeiten: deque[float] = deque()

    def absturz(self, jetzt: float) -> bool:
        """Zählt einen Absturz. False heißt: aufgeben."""
        self._zeiten.append(jetzt)
        while self._zeiten and jetzt - self._zeiten[0] > self._fenster_s:
            self._zeiten.popleft()
        return len(self._zeiten) < self._max


class SensorThread(threading.Thread):
    def __init__(self, name: str, schritt: Callable[[], list], intervall_s: float,
                 ausgabe: Callable[[object], None], fehler: Callable[[str, str], None],
                 uhr: Uhr = time.time, neustart_s: float = 5.0, beim_stopp: Callable[[], None] | None = None):
        super().__init__(name=name, daemon=True)
        self._schritt = schritt
        self._intervall_s = intervall_s
        self._ausgabe = ausgabe
        self._fehler = fehler
        self._uhr = uhr
        self._neustart_s = neustart_s
        self._beim_stopp = beim_stopp
        self._stopp = threading.Event()
        self._zaehler = AbsturzZaehler()

    def stoppe(self) -> None:
        self._stopp.set()

    def run(self) -> None:
        try:
            while not self._stopp.is_set():
                try:
                    for eintrag in self._schritt():
                        self._ausgabe(eintrag)
                except Exception as e:
                    self._fehler(self.name, repr(e))
                    if not self._zaehler.absturz(self._uhr()):
                        self._fehler(self.name, AUFGEGEBEN)
                        return
                    if self._stopp.wait(self._neustart_s):
                        return
                    continue
                self._stopp.wait(self._intervall_s)
        finally:
            if self._beim_stopp is not None:
                try:
                    self._beim_stopp()
                except Exception:
                    pass
