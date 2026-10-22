"""PC-Sensor: Vordergrundfenster, Prozess und URL."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

from ..clock import Uhr
from ..decision.rules import BROWSER_PROZESSE, domain_aus_url
from ..models import PcBeobachtung

URL_LESBAR = frozenset({"chrome.exe", "msedge.exe", "brave.exe"})


def beobachtung_aus(zeit: float, fenster_id: int, prozess: str, titel: str, url: str | None) -> PcBeobachtung:
    prozess = prozess.lower()
    return PcBeobachtung(zeit, fenster_id, prozess, titel, url, domain_aus_url(url), prozess in BROWSER_PROZESSE)


class PcSensor:
    def __init__(self, lies_vordergrund: Callable[[], tuple[int, int, str, str] | None],
                 lies_url: Callable[[int, str], str | None], uhr: Uhr, eigene_pid: int):
        self._lies_vordergrund = lies_vordergrund
        self._lies_url = lies_url
        self._uhr = uhr
        self._eigene_pid = eigene_pid
        self._url_schluessel: tuple[int, str] | None = None
        self._url: str | None = None
        self._letzte: PcBeobachtung | None = None

    def schritt(self) -> list[PcBeobachtung]:
        vorne = self._lies_vordergrund()
        if vorne is None:
            return []
        fenster_id, pid, prozess, titel = vorne
        if pid == self._eigene_pid:
            # Eigene Fenster (Overlay, Dialoge) werden nie beurteilt: das zuletzt aktive fremde Fenster gilt weiter.
            return [replace(self._letzte, zeit=self._uhr())] if self._letzte is not None else []
        url = None
        if prozess.lower() in URL_LESBAR:
            schluessel = (fenster_id, titel)
            if schluessel != self._url_schluessel:
                self._url_schluessel = schluessel
                try:
                    self._url = self._lies_url(fenster_id, prozess.lower())
                except Exception:
                    self._url = None
            url = self._url
        self._letzte = beobachtung_aus(self._uhr(), fenster_id, prozess, titel, url)
        return [self._letzte]


def windows_vordergrund() -> tuple[int, int, str, str] | None:
    import psutil
    import win32gui
    import win32process

    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    try:
        name = psutil.Process(pid).name()
    except psutil.Error:
        name = "unbekannt"
    return hwnd, pid, name, win32gui.GetWindowText(hwnd)


def windows_url(fenster_id: int, prozess: str) -> str | None:
    try:
        import uiautomation as auto

        with auto.UIAutomationInitializerInThread(debug=False):
            auto.SetGlobalSearchTimeout(0.5)
            fenster = auto.ControlFromHandle(fenster_id)
            if fenster is None:
                return None
            adresse = fenster.EditControl(searchDepth=12)
            if not adresse.Exists(0, 0):
                return None
            return adresse.GetValuePattern().Value or None
    except Exception:
        return None
