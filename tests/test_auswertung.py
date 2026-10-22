import pytest

from focusguard.auswertung import berechne
from focusguard.models import Session, Ereignis, Status


def ev(t, art, quelle="", status="", **details):
    return Ereignis(t, art, quelle, status, details)


SESSION = Session(1, "Blender", "blender", 0.0, 50, ende=600.0, vorzeitig_beendet=True)
EREIGNISSE = [
    ev(0, "statuswechsel", "", "fokus"), ev(100, "statuswechsel", "domain:instagram.com", "abgelenkt"),
    ev(110, "eskalation", "domain:instagram.com", "abgelenkt", stufe=1), ev(160, "statuswechsel", "", "fokus"),
    ev(200, "statuswechsel", "handy", "abgelenkt"), ev(210, "statuswechsel", "", "fokus"),
    ev(400, "statuswechsel", "", "abwesend"), ev(500, "statuswechsel", "", "fokus"),
    ev(50, "ki_aufruf", "seite:a|b", "fokus", tokens_ein=900_000, tokens_aus=50_000),
    ev(60, "ki_aufruf", "stichprobe", "", tokens_ein=100_000, tokens_aus=50_000),
    ev(170, "sperre", "domain:instagram.com"), ev(180, "sperre_aufgehoben"), ev(190, "korrektur", "handy")]


def test_zeiten_und_fokusquote():
    a = berechne(SESSION, EREIGNISSE, "claude-haiku-5-5", 999)
    assert a.sekunden[Status.FOKUS] == 430 and a.sekunden[Status.ABGELENKT] == 70 and a.sekunden[Status.ABWESEND] == 100
    assert a.fokusquote == pytest.approx(430 / 500)
    assert (a.dauer_min, a.geplant_min, a.vorzeitig) == (10, 50, True)


def test_top_und_zaehler():
    a = berechne(SESSION, EREIGNISSE, "claude-haiku-5-5", 999)
    assert a.top_ablenkungen == [("domain:instagram.com", 1, 60.0), ("handy", 1, 10.0)]
    assert a.eskalationen == {1: 1} and (a.sperren, a.aufhebungen, a.korrekturen, a.ki_aufrufe) == (1, 1, 1, 2)
    assert a.kosten_usd == pytest.approx(0.15)


def test_unbekanntes_modell_und_laufende_session():
    assert berechne(SESSION, EREIGNISSE, "anderes", 999).kosten_usd is None
    laufend = Session(2, "a", "a", 0.0, 25)
    a = berechne(laufend, [ev(0, "statuswechsel", "", "fokus")], "claude-haiku-5-5", 120.0)
    assert a.sekunden[Status.FOKUS] == 120 and a.fokusquote == 1.0


def test_nur_abwesend_ohne_quote():
    s = Session(3, "a", "a", 0.0, 25, ende=60.0)
    assert berechne(s, [ev(0, "statuswechsel", "", "abwesend")], "claude-haiku-5-5", 60).fokusquote is None
