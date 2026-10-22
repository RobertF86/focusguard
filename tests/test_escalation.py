from focusguard.escalation import Eskalation
from focusguard.models import (Urteil, Status, OverlayZeigen, OverlaySchliessen, Sperren,
                               HandyOverlay, Begruessung, IconStatus)
from hilfen import einst

ABG = lambda q="domain:instagram.com", seit=None: Urteil(Status.ABGELENKT, q, "Instagram", "regel", seit)
FOK = Urteil(Status.FOKUS, "", "", "lokal")
WEG = Urteil(Status.ABWESEND, "", "", "lokal")


def esk():
    e = einst()
    return Eskalation(e.eskalation, e.erkennung.begruessung_ab_minuten, 0.0)


def lauf(es, urteil, von, bis):
    out = []
    for t in range(von, bis + 1):
        out += [(t, a) for a in es.schritt(urteil, float(t))]
    return out


def typen(aktionen):
    return [(t, type(a).__name__) for t, a in aktionen if not isinstance(a, IconStatus)]


def test_stufen_10_40_70():
    a = lauf(esk(), ABG(), 0, 75)
    assert typen(a) == [(10, "Hinweis"), (40, "OverlayZeigen"), (70, "Sperren")]
    assert (10, IconStatus("gelb")) in a and (40, IconStatus("rot")) in a
    assert (70, Sperren("domain:instagram.com")) in a


def test_ende_schliesst_overlay():
    es = esk()
    lauf(es, ABG(), 0, 45)
    assert es.schritt(FOK, 46) == [OverlaySchliessen(), IconStatus("gruen")]


def test_rueckfall_eine_stufe_hoeher_und_vergessen():
    es = esk()
    lauf(es, ABG(), 0, 15)
    lauf(es, FOK, 16, 60)
    assert typen(lauf(es, ABG(), 61, 101)) == [(71, "OverlayZeigen"), (101, "Sperren")]
    es2 = esk()
    lauf(es2, ABG(), 0, 15)
    lauf(es2, FOK, 16, 400)
    assert typen(lauf(es2, ABG(), 401, 412)) == [(411, "Hinweis")]


def test_quellenwechsel_setzt_uhr_nicht_zurueck():
    es = esk()
    lauf(es, ABG(), 0, 20)
    a = lauf(es, ABG("domain:tiktok.com"), 21, 45)
    assert (40, OverlayZeigen("Instagram", "domain:tiktok.com")) in a


def test_stufe3_sperrt_jede_neue_quelle():
    es = esk()
    lauf(es, ABG(), 0, 72)
    assert (73, Sperren("domain:tiktok.com")) in lauf(es, ABG("domain:tiktok.com"), 73, 75)


def test_stichprobe_hoechstens_stufe_2_und_seit():
    es = esk()
    a = lauf(es, ABG("stichprobe", seit=0.0), 30, 100)
    assert typen(a) == [(30, "Hinweis"), (40, "OverlayZeigen")]


def test_handy_overlay_bis_5_s_ohne_handy():
    es = esk()
    a = lauf(es, ABG("handy"), 0, 75)
    assert (70, HandyOverlay()) in a
    assert typen(lauf(es, FOK, 76, 79)) == []
    assert (80, OverlaySchliessen()) in lauf(es, FOK, 80, 80)


def test_zurueck_zur_aufgabe():
    es = esk()
    lauf(es, ABG(), 0, 45)
    assert es.zurueck_zur_aufgabe(45) == [OverlaySchliessen()]
    assert typen(lauf(es, ABG(), 46, 50)) == [(50, "OverlayZeigen")]


def test_korrektur_ohne_rueckfall():
    es = esk()
    lauf(es, ABG(), 0, 45)
    assert es.korrektur(45) == [OverlaySchliessen(), IconStatus("gruen")]
    lauf(es, FOK, 46, 59)
    assert typen(lauf(es, ABG(), 60, 70)) == [(70, "Hinweis")]


def test_abwesend_icon_und_begruessung():
    es = esk()
    a = lauf(es, WEG, 0, 400)
    assert [x for _, x in a if isinstance(x, IconStatus)] == [IconStatus("blau")]
    assert Begruessung(6) in es.schritt(FOK, 401)
    es2 = esk()
    lauf(es2, WEG, 0, 100)
    assert not any(isinstance(x, Begruessung) for x in es2.schritt(FOK, 101))
