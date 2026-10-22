"""Auswertung einer Session aus ihren Ereignissen."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .models import Ereignis, Session, Status

# USD pro Million Eingabe-/Ausgabe-Tokens
PREISE: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}


@dataclass(frozen=True)
class Auswertung:
    session_id: int
    aufgabe: str
    start: float
    dauer_min: int
    geplant_min: int
    vorzeitig: bool
    sekunden: dict[Status, float]
    fokusquote: float | None
    top_ablenkungen: list[tuple[str, int, float]]
    eskalationen: dict[int, int]
    sperren: int
    aufhebungen: int
    korrekturen: int
    ki_aufrufe: int
    kosten_usd: float | None


def berechne(session: Session, ereignisse: list[Ereignis], modell: str, jetzt: float) -> Auswertung:
    ende = session.ende if session.ende is not None else jetzt
    sortiert = sorted(ereignisse, key=lambda e: e.zeit)

    sekunden = {s: 0.0 for s in Status}
    ablenkung_dauer: dict[str, float] = {}
    ablenkung_anzahl: Counter[str] = Counter()
    wechsel = [e for e in sortiert if e.art == "statuswechsel"]
    for i, e in enumerate(wechsel):
        bis = wechsel[i + 1].zeit if i + 1 < len(wechsel) else ende
        dauer = max(0.0, min(bis, ende) - e.zeit)
        status = Status(e.status)
        sekunden[status] += dauer
        if status is Status.ABGELENKT:
            ablenkung_dauer[e.quelle] = ablenkung_dauer.get(e.quelle, 0.0) + dauer
            ablenkung_anzahl[e.quelle] += 1

    anwesend = sum(sekunden.values()) - sekunden[Status.ABWESEND]
    fokusquote = sekunden[Status.FOKUS] / anwesend if anwesend > 0 else None
    top = sorted(((q, ablenkung_anzahl[q], d) for q, d in ablenkung_dauer.items()), key=lambda x: -x[2])[:5]

    eskalationen: Counter[int] = Counter()
    zaehler: Counter[str] = Counter()
    tokens_ein = tokens_aus = 0
    for e in sortiert:
        zaehler[e.art] += 1
        if e.art == "eskalation" and "stufe" in e.details:
            eskalationen[int(e.details["stufe"])] += 1
        elif e.art == "ki_aufruf":
            tokens_ein += int(e.details.get("tokens_ein", 0) or 0)
            tokens_aus += int(e.details.get("tokens_aus", 0) or 0)

    preis = PREISE.get(modell)
    kosten = (tokens_ein * preis[0] + tokens_aus * preis[1]) / 1_000_000 if preis else None

    return Auswertung(
        session_id=session.id, aufgabe=session.aufgabe, start=session.start,
        dauer_min=round((ende - session.start) / 60), geplant_min=session.geplant_min,
        vorzeitig=session.vorzeitig_beendet, sekunden=sekunden, fokusquote=fokusquote, top_ablenkungen=top,
        eskalationen=dict(eskalationen), sperren=zaehler["sperre"], aufhebungen=zaehler["sperre_aufgehoben"],
        korrekturen=zaehler["korrektur"], ki_aufrufe=zaehler["ki_aufruf"], kosten_usd=kosten)
