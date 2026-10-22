"""Auswertungsfenster: letzte Session und Verlauf der letzten 7 Tage."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QDialog, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout

from ..auswertung import Auswertung
from ..models import Status


def lesbare_quelle(quelle: str) -> str:
    if quelle == "handy":
        return "Handy"
    if quelle == "stichprobe":
        return "Stichprobe"
    for praefix in ("domain:", "prozess:"):
        if quelle.startswith(praefix):
            return quelle.removeprefix(praefix)
    if quelle.startswith("seite:"):
        ort, _, titel = quelle.removeprefix("seite:").partition("|")
        return f"{titel} ({ort})" if titel else ort
    return quelle or "–"


def _dauer(sekunden: float) -> str:
    return f"{round(sekunden)} s" if sekunden < 60 else f"{round(sekunden / 60)} min"


def _quote(q: float | None) -> str:
    return "–" if q is None else f"{q:.0%}"


class AuswertungsFenster(QDialog):
    def __init__(self, a: Auswertung, verlauf: list[Auswertung], parent=None):
        super().__init__(parent)
        self.setWindowTitle("FocusGuard – Auswertung")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)

        def zeile(text: str) -> None:
            label = QLabel(text)
            label.setWordWrap(True)
            layout.addWidget(label)

        zeile(f"<b>{a.aufgabe}</b>")
        zeile(f"Fokusquote: {_quote(a.fokusquote)}")
        if a.vorzeitig:
            zeile(f"vorzeitig beendet nach {a.dauer_min} von {a.geplant_min} min")
        else:
            zeile(f"Dauer: {a.dauer_min} min")
        namen = {Status.FOKUS: "Fokus", Status.UNKLAR: "Unklar", Status.ABGELENKT: "Abgelenkt",
                 Status.ABWESEND: "Abwesend"}
        zeile(" · ".join(f"{namen[s]}: {_dauer(a.sekunden.get(s, 0.0))}" for s in namen))
        if a.top_ablenkungen:
            zeile("Häufigste Ablenkungen:<br>" + "<br>".join(
                f"{lesbare_quelle(q)}: {n}×, {_dauer(d)}" for q, n, d in a.top_ablenkungen))
        else:
            zeile("Keine Ablenkungen erkannt.")
        zeile("Eskalationen: " + " · ".join(f"Stufe {s}: {a.eskalationen.get(s, 0)}" for s in (1, 2, 3)))
        zeile(f"Sperren: {a.sperren} · aufgehoben: {a.aufhebungen} · Korrekturen: {a.korrekturen}")
        kosten = "" if a.kosten_usd is None else f" (ca. {a.kosten_usd:.2f} $)"
        zeile(f"KI-Aufrufe: {a.ki_aufrufe}{kosten}")

        zeile("<b>Letzte 7 Tage</b>")
        tabelle = QTableWidget(len(verlauf), 4)
        tabelle.setHorizontalHeaderLabels(["Datum", "Aufgabe", "Dauer", "Fokusquote"])
        for i, v in enumerate(verlauf):
            werte = [datetime.fromtimestamp(v.start).strftime("%d.%m. %H:%M"), v.aufgabe, f"{v.dauer_min} min",
                     _quote(v.fokusquote)]
            for j, wert in enumerate(werte):
                tabelle.setItem(i, j, QTableWidgetItem(wert))
        tabelle.resizeColumnsToContents()
        layout.addWidget(tabelle)
