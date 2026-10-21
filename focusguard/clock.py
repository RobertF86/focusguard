"""Uhr-Abstraktion: echte Uhr für die App, steuerbare Uhr für Tests."""

import time
from typing import Callable

Uhr = Callable[[], float]

echte_uhr: Uhr = time.time


class TestUhr:
    __test__ = False  # keine pytest-Testklasse

    def __init__(self, start: float = 0.0):
        self._jetzt = start

    def __call__(self) -> float:
        return self._jetzt

    def vor(self, sekunden: float) -> None:
        self._jetzt += sekunden

    def setze(self, t: float) -> None:
        self._jetzt = t
