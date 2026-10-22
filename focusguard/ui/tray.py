"""Tray-Icon mit Menü; setzt den OberflaechePort der Steuerung um."""

from __future__ import annotations

import sys
from typing import Callable

from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..auswertung import Auswertung
from .icons import farbiges_icon
from .overlay import Overlay
from .report import AuswertungsFenster


class Tray:
    """Komposition statt Vererbung, damit `icon(farbe)` nicht QSystemTrayIcon.icon() überschreibt."""

    def __init__(self, *, sensoren: tuple[bool, bool, bool], bei_start: Callable[[], None],
                 bei_ende: Callable[[], None], bei_sensor: Callable[[str, bool], None],
                 bei_aufheben: Callable[[], None], bei_einstellungen: Callable[[], None],
                 bei_auswertung: Callable[[], None], bei_beenden: Callable[[], None],
                 zurueck: Callable[[], None], gehoert: Callable[[str], None]):
        self._symbol = QSystemTrayIcon(farbiges_icon("grau"))
        self._menue = QMenu()
        self._start = self._menue.addAction("Session starten …")
        self._start.triggered.connect(lambda: bei_start())
        self._ende = self._menue.addAction("Session beenden")
        self._ende.triggered.connect(lambda: bei_ende())
        self._menue.addSeparator()
        for name, text, wert in zip(("pc", "webcam", "smartphone"), ("PC", "Webcam", "Smartphone"), sensoren):
            aktion = self._menue.addAction(text)
            aktion.setCheckable(True)
            aktion.setChecked(wert)
            aktion.toggled.connect(lambda an, n=name: bei_sensor(n, an))
        self._menue.addSeparator()
        self._aufheben = self._menue.addAction("Sperren aufheben")
        self._aufheben.triggered.connect(lambda: bei_aufheben())
        self._menue.addAction("Einstellungen …").triggered.connect(lambda: bei_einstellungen())
        self._menue.addAction("Auswertung …").triggered.connect(lambda: bei_auswertung())
        self._menue.addSeparator()
        self._menue.addAction("Beenden").triggered.connect(lambda: bei_beenden())
        self._symbol.setContextMenu(self._menue)
        self._symbol.setToolTip("FocusGuard – keine Session")
        self._overlay = Overlay(zurueck, gehoert)
        self._fenster: list[AuswertungsFenster] = []
        self.setze_session_aktiv(False)

    def contextMenu(self) -> QMenu:
        return self._menue

    def show(self) -> None:
        self._symbol.show()

    def hide(self) -> None:
        self._symbol.hide()

    def setze_session_aktiv(self, aktiv: bool) -> None:
        self._start.setEnabled(not aktiv)
        self._ende.setEnabled(aktiv)
        self._aufheben.setEnabled(aktiv)

    # --- OberflaechePort ------------------------------------------------------------------------

    def hinweis(self, text: str) -> None:
        self._symbol.showMessage("FocusGuard", text, QSystemTrayIcon.Information, 8000)
        if sys.platform == "win32":
            try:
                import winsound

                winsound.MessageBeep()
            except Exception:
                pass

    def overlay_zeigen(self, titel: str, text: str, quelle: str) -> None:
        self._overlay.zeige(titel, text, quelle)

    def overlay_schliessen(self) -> None:
        self._overlay.schliesse()

    def icon(self, farbe: str) -> None:
        self._symbol.setIcon(farbiges_icon(farbe))

    def tooltip(self, text: str) -> None:
        self._symbol.setToolTip(text)

    def zeige_auswertung(self, a: Auswertung, verlauf: list[Auswertung]) -> None:
        fenster = AuswertungsFenster(a, verlauf)
        fenster.finished.connect(lambda _=None, f=fenster: self._fenster.remove(f) if f in self._fenster else None)
        self._fenster.append(fenster)
        fenster.show()
        fenster.raise_()
