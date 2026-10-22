"""Farbige Kreis-Icons für das Tray."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

FARBEN = {"grau": "#8a8a8a", "gruen": "#2e9d4f", "gelb": "#e0a800", "rot": "#d64545", "blau": "#3d7bd9"}


def farbiges_icon(farbe: str) -> QIcon:
    bild = QPixmap(64, 64)
    bild.fill(Qt.transparent)
    maler = QPainter(bild)
    maler.setRenderHint(QPainter.Antialiasing)
    maler.setPen(Qt.NoPen)
    maler.setBrush(QColor(FARBEN.get(farbe, FARBEN["grau"])))
    maler.drawEllipse(4, 4, 56, 56)
    maler.end()
    return QIcon(bild)
