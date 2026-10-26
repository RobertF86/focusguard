"""Startdialog: Aufgabe und Dauer, dann die Listen (gespeichert oder von der KI vorgeschlagen)."""

from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from ..decision.rules import domain_aus_url
from ..models import AufgabenListen

_FELDER = (("fokus_programme", "Fokus-Programme"), ("fokus_domains", "Fokus-Domains"),
           ("ablenkung_programme", "Ablenkende Programme"), ("ablenkung_domains", "Ablenkende Domains"))


def _standard_ausfuehren(arbeit: Callable[[], None]) -> None:
    threading.Thread(target=arbeit, daemon=True).start()


class StartDialog(QDialog):
    _listen_bereit = Signal(object)

    def __init__(self, gespeicherte_listen: Callable[[str], AufgabenListen | None],
                 vorschlagen: Callable[[str], AufgabenListen | None],
                 ausfuehren: Callable[[Callable[[], None]], None] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("FocusGuard – Session starten")
        self.setMinimumWidth(460)
        self._gespeicherte = gespeicherte_listen
        self._vorschlagen = vorschlagen
        self._ausfuehren = ausfuehren or _standard_ausfuehren
        self._ergebnis: tuple[str, int, AufgabenListen] | None = None
        self._listen_bereit.connect(self._fuelle)

        self._seiten = QStackedWidget()
        layout = QVBoxLayout(self)
        layout.addWidget(self._seiten)
        self._seiten.addWidget(self._seite_aufgabe())
        self._seiten.addWidget(self._seite_listen())

    def _seite_aufgabe(self) -> QWidget:
        seite = QWidget()
        form = QFormLayout(seite)
        self._aufgabe = QLineEdit()
        self._aufgabe.setObjectName("aufgabe")
        self._aufgabe.setPlaceholderText("z. B. Blender-Grundlagen lernen")
        form.addRow("Aufgabe:", self._aufgabe)

        self._dauer = QComboBox()
        for minuten in (25, 50, 90):
            self._dauer.addItem(f"{minuten} Minuten", minuten)
        self._dauer.addItem("frei", None)
        self._frei = QSpinBox()
        self._frei.setRange(1, 240)
        self._frei.setValue(45)
        self._frei.setSuffix(" min")
        self._frei.setEnabled(False)
        self._dauer.currentIndexChanged.connect(lambda _: self._frei.setEnabled(self._dauer.currentData() is None))
        dauer_zeile = QHBoxLayout()
        dauer_zeile.addWidget(self._dauer)
        dauer_zeile.addWidget(self._frei)
        form.addRow("Dauer:", dauer_zeile)

        self._weiter = QPushButton("Weiter")
        self._weiter.setEnabled(False)
        self._weiter.setDefault(True)
        self._aufgabe.textChanged.connect(lambda t: self._weiter.setEnabled(bool(t.strip())))
        self._weiter.clicked.connect(self._weiter_geklickt)
        form.addRow(self._weiter)
        return seite

    def _seite_listen(self) -> QWidget:
        seite = QWidget()
        layout = QVBoxLayout(seite)
        self._wartet = QLabel("KI schlägt Listen vor …")
        self._wartet.hide()
        layout.addWidget(self._wartet)
        layout.addWidget(QLabel("Ein Eintrag pro Zeile. Du kannst die Listen frei anpassen."))
        self._listen_felder: dict[str, QPlainTextEdit] = {}
        for name, titel in _FELDER:
            layout.addWidget(QLabel(titel))
            feld = QPlainTextEdit()
            feld.setFixedHeight(70)
            self._listen_felder[name] = feld
            layout.addWidget(feld)
        self._starten = QPushButton("Session starten")
        self._starten.setDefault(True)
        self._starten.clicked.connect(self._starten_geklickt)
        layout.addWidget(self._starten)
        return seite

    def _weiter_geklickt(self) -> None:
        aufgabe = self._aufgabe.text().strip()
        if not aufgabe:
            return
        self._seiten.setCurrentIndex(1)
        gespeichert = self._gespeicherte(aufgabe)
        if gespeichert is not None and not gespeichert.ist_leer():
            self._fuelle(gespeichert)
            return
        self._wartet.show()

        def arbeit() -> None:
            try:
                listen = self._vorschlagen(aufgabe)
            except Exception:
                listen = None
            self._listen_bereit.emit(listen)

        self._ausfuehren(arbeit)

    def _fuelle(self, listen: AufgabenListen | None) -> None:
        self._wartet.hide()
        if listen is None:
            return
        for name, feld in self._listen_felder.items():
            # Was schon im Feld steht (etwa während der KI-Anfrage getippt), bleibt; Vorschläge kommen dazu.
            zeilen = [z.strip() for z in feld.toPlainText().splitlines() if z.strip()]
            vorhanden = {z.lower() for z in zeilen}
            zeilen += [w for w in getattr(listen, name) if w.lower() not in vorhanden]
            feld.setPlainText("\n".join(zeilen))

    def _lies_liste(self, name: str) -> tuple[str, ...]:
        werte: list[str] = []
        for zeile in self._listen_felder[name].toPlainText().splitlines():
            wert = domain_aus_url(zeile) if name.endswith("domains") else zeile.strip().lower()
            if wert and wert not in werte:
                werte.append(wert)
        return tuple(werte)

    def _starten_geklickt(self) -> None:
        dauer = self._dauer.currentData()
        if dauer is None:
            dauer = self._frei.value()
        listen = AufgabenListen(**{name: self._lies_liste(name) for name, _ in _FELDER})
        self._ergebnis = (self._aufgabe.text().strip(), int(dauer), listen)
        self.accept()

    def ergebnis(self) -> tuple[str, int, AufgabenListen] | None:
        return self._ergebnis
