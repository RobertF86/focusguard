from focusguard.decision.kamera_regeln import KameraBewerter
from focusguard.models import WebcamBeobachtung as W, HandyBeobachtung as H, KiUrteil, Status
from hilfen import einst


def kb(webcam=True, smartphone=True):
    e = einst()
    return KameraBewerter(e.erkennung, e.ki.handy_pruefung_sekunden, 0.0, webcam, smartphone)


def gesichter(k, von, bis, pitch=5.0, schritt=0.5):
    t = von
    while t <= bis:
        k.webcam(W(t, True, pitch))
        t += schritt


def handy_mit_kopf(k, start, anzahl, pitch, schritt=0.5):
    for i in range(anzahl):
        t = start + i * schritt
        k.webcam(W(t, True, pitch))
        k.handy(H(t, True, 0.8))


def test_abwesend_nach_15_s_ohne_gesicht():
    k = kb()
    k.webcam(W(0, True, 5))
    for t in range(1, 17):
        k.webcam(W(t, False, None))
    assert k.urteil(14.5) is None
    assert k.urteil(16.5).status is Status.ABWESEND


def test_kein_abwesend_wenn_webcam_aus():
    k = kb(webcam=False)
    k.webcam(W(0, True, 5))
    for t in range(1, 30):
        k.webcam(W(t, False, None))
    assert k.urteil(29.5) is None


def test_kein_abwesend_wenn_keine_bilder_mehr_kommen():
    k = kb()
    k.webcam(W(0, True, 5))
    assert k.urteil(30) is None


def test_handy_kopf_gesenkt_nach_3_s():
    k = kb()
    gesichter(k, 0, 10)                     # baseline 5
    handy_mit_kopf(k, 10.5, 7, 30)          # 10.5 .. 13.5
    u = k.urteil(12.5)
    assert u is None or u.status is not Status.ABGELENKT
    u = k.urteil(13.5)
    assert (u.status, u.quelle, u.herkunft) == (Status.ABGELENKT, "handy", "lokal")


def test_handy_luecke_bis_1_s_unterbricht_nicht():
    k = kb()
    gesichter(k, 0, 10)
    for t in (10.5, 11.5, 12.5, 13.5):
        k.webcam(W(t, True, 30))
        k.handy(H(t, True, 0.8))
    assert k.urteil(13.5).status is Status.ABGELENKT


def test_baseline_relativ():
    k = kb()
    gesichter(k, 0, 10, pitch=15)           # baseline 15
    handy_mit_kopf(k, 10.5, 8, 30)
    assert k.urteil(14.0).status is Status.UNKLAR   # 30 - 15 < 20


def test_handy_kopf_oben_ki_hoechstens_alle_60_s():
    k = kb()
    gesichter(k, 0, 10)
    handy_mit_kopf(k, 10.5, 8, 5)
    assert k.urteil(14.0).status is Status.UNKLAR and k.braucht_ki(14.0)
    k.ki_angefragt(14.0)
    assert not k.braucht_ki(20.0)
    k.ki_ergebnis(KiUrteil(Status.ABGELENKT, "Du tippst auf dem Handy", 0.9, "seite"), 15.0)
    assert k.urteil(14.0).herkunft == "ki"


def test_ki_fehler_neuer_versuch_nach_30_s():
    k = kb()
    gesichter(k, 0, 10)
    handy_mit_kopf(k, 10.5, 8, 5)
    k.ki_angefragt(14.0)
    k.ki_ergebnis(None, 14.0)
    handy_mit_kopf(k, 14.5, 70, 5)
    assert not k.braucht_ki(43.0) and k.braucht_ki(44.5)


def test_handy_aussetzen_und_ohne_gesicht():
    k = kb()
    gesichter(k, 0, 10)
    k.handy_aussetzen(200.0)
    handy_mit_kopf(k, 10.5, 8, 30)
    assert k.urteil(14.0) is None
    k2 = kb()
    k2.handy(H(1, True, 0.9))
    k2.handy(H(5, True, 0.9))
    assert k2.urteil(5) is None              # no face → no phone rules


def test_handy_frei_seit():
    k = kb()
    k.handy(H(10, True, 0.9))
    k.handy(H(11, False, 0.1))
    assert k.handy_frei_seit(16) == 6
