"""Sperre ohne Admin-Rechte: Programme minimieren, Browser-Tabs schließen."""

from __future__ import annotations

import math
from typing import Callable, Iterable

from .clock import Uhr
from .decision.memory import seiten_schluessel
from .decision.rules import domain_passt, programm_passt
from .models import AufgabenListen, PcBeobachtung

ABKLINGZEIT_S = 2.0


def sperr_aktion(b: PcBeobachtung, gesperrt: Iterable[str], nie_sperren: Iterable[str],
                 fokus: AufgabenListen) -> str | None:
    if programm_passt(b.prozess, nie_sperren) or programm_passt(b.prozess, fokus.fokus_programme):
        return None
    if b.domain and domain_passt(b.domain, fokus.fokus_domains):
        return None
    for quelle in gesperrt:
        if quelle.startswith("domain:"):
            if b.ist_browser and b.domain and domain_passt(b.domain, [quelle.removeprefix("domain:")]):
                return "tab_schliessen"
        elif quelle.startswith("seite:"):
            if seiten_schluessel(b) == quelle.removeprefix("seite:"):
                return "tab_schliessen" if b.ist_browser else "minimieren"
        elif quelle.startswith("prozess:"):
            if programm_passt(b.prozess, [quelle.removeprefix("prozess:")]):
                return "minimieren"
    return None


class Blocker:
    def __init__(self, nie_sperren: Iterable[str], uhr: Uhr, minimiere: Callable[[int], None],
                 strg_w: Callable[[], None], vordergrund: Callable[[], int]):
        self._nie_sperren = tuple(nie_sperren)
        self._uhr = uhr
        self._minimiere = minimiere
        self._strg_w = strg_w
        self._vordergrund = vordergrund
        self._zuletzt = -math.inf

    def pruefe(self, b: PcBeobachtung, gesperrt: Iterable[str], fokus: AufgabenListen) -> str | None:
        aktion = sperr_aktion(b, gesperrt, self._nie_sperren, fokus)
        if aktion is None:
            return None
        jetzt = self._uhr()
        if jetzt - self._zuletzt < ABKLINGZEIT_S:
            return None
        try:
            if self._vordergrund() != b.fenster_id:
                return None
            self._zuletzt = jetzt
            if aktion == "tab_schliessen":
                self._strg_w()
            else:
                self._minimiere(b.fenster_id)
        except Exception:
            return "fehler"
        return aktion


def windows_blocker(nie_sperren: Iterable[str], uhr: Uhr) -> Blocker:
    def minimiere(hwnd: int) -> None:
        import win32con
        import win32gui

        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)

    def strg_w() -> None:
        import win32api
        import win32con

        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        win32api.keybd_event(ord("W"), 0, 0, 0)
        win32api.keybd_event(ord("W"), 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)

    def vordergrund() -> int:
        import win32gui

        return win32gui.GetForegroundWindow()

    return Blocker(nie_sperren, uhr, minimiere, strg_w, vordergrund)
