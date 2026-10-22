"""Vollbild-Overlay über allen Monitoren."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

_STIL = """
QWidget { background-color: #14161a; color: #f2f2f2; }
QPushButton { background-color: #2b2f36; border: 1px solid #4a505a; border-radius: 6px; padding: 12px 24px;
              font-size: 16px; }
QPushButton:hover { background-color: #3a3f48; }
"""


class _OverlayFenster(QWidget):
    def __init__(self, bei_esc: Callable[[], None]):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self._bei_esc = bei_esc
        self.setWindowOpacity(0.92)
        self.setStyleSheet(_STIL)

    def keyPressEvent(self, ereignis):
        if ereignis.key() == Qt.Key_Escape:
            self._bei_esc()
        else:
            super().keyPressEvent(ereignis)


class Overlay:
    def __init__(self, zurueck: Callable[[], None], gehoert: Callable[[str], None]):
        self._zurueck = zurueck
        self._gehoert = gehoert
        self._quelle = ""
        self.fenster: list[QWidget] = []

    @property
    def ist_offen(self) -> bool:
        return bool(self.fenster)

    def zeige(self, titel: str, text: str, quelle: str) -> None:
        self.schliesse()
        self._quelle = quelle
        primaer = QGuiApplication.primaryScreen()
        bildschirme = [primaer] + [s for s in QGuiApplication.screens() if s is not primaer]
        for i, bildschirm in enumerate(bildschirme):
            fenster = _OverlayFenster(self._zurueck_gedrueckt)
            if i == 0:
                self._inhalt(fenster, titel, text)
            if bildschirm is not None:
                fenster.setGeometry(bildschirm.geometry())
            fenster.show()
            fenster.raise_()
            fenster.activateWindow()
            self.fenster.append(fenster)

    def _inhalt(self, fenster: QWidget, titel: str, text: str) -> None:
        layout = QVBoxLayout(fenster)
        layout.addStretch()
        ueberschrift = QLabel(titel)
        schrift = QFont()
        schrift.setPointSize(28)
        schrift.setBold(True)
        ueberschrift.setFont(schrift)
        ueberschrift.setAlignment(Qt.AlignCenter)
        ueberschrift.setWordWrap(True)
        layout.addWidget(ueberschrift)
        beschreibung = QLabel(text)
        beschreibung.setAlignment(Qt.AlignCenter)
        beschreibung.setWordWrap(True)
        beschreibung.setStyleSheet("font-size: 18px; color: #c9ccd1;")
        layout.addWidget(beschreibung)
        knoepfe = QHBoxLayout()
        knoepfe.addStretch()
        zurueck = QPushButton("Zurück zur Aufgabe")
        zurueck.clicked.connect(self._zurueck_gedrueckt)
        zurueck.setDefault(True)
        gehoert = QPushButton("Gehört zur Aufgabe")
        gehoert.clicked.connect(self._gehoert_gedrueckt)
        knoepfe.addWidget(zurueck)
        knoepfe.addWidget(gehoert)
        knoepfe.addStretch()
        layout.addSpacing(24)
        layout.addLayout(knoepfe)
        layout.addStretch()

    def _zurueck_gedrueckt(self) -> None:
        self.schliesse()
        self._zurueck()

    def _gehoert_gedrueckt(self) -> None:
        quelle = self._quelle
        self.schliesse()
        self._gehoert(quelle)

    def schliesse(self) -> None:
        for fenster in self.fenster:
            fenster.close()
            fenster.deleteLater()
        self.fenster = []
