from focusguard.decision.memory import seiten_schluessel, eintrag_fuer, quelle_fuer, Gedaechtnis
from focusguard.models import KiUrteil, Status, GedaechtnisEintrag
from hilfen import pc

YT = pc(url="https://youtube.com/watch?v=1", titel="Blender Donut")


def test_seiten_schluessel():
    assert seiten_schluessel(YT) == "youtube.com|Blender Donut"
    assert seiten_schluessel(pc("blender.exe", titel="x")) == "blender.exe|x"


def test_eintrag_ebenen():
    assert eintrag_fuer(YT, KiUrteil(Status.FOKUS, "ok", 0.9, "domain"), "k", 1.0).schluessel == "youtube.com"
    assert eintrag_fuer(pc("firefox.exe", titel="T"), KiUrteil(Status.FOKUS, "ok", 0.9, "domain"), "k", 1.0).ebene == "seite"
    assert eintrag_fuer(YT, KiUrteil(Status.FOKUS, "ok", 0.9, "programm"), "k", 1.0).ebene == "seite"
    assert eintrag_fuer(pc("blender.exe"), KiUrteil(Status.FOKUS, "ok", 0.9, "programm"), "k", 1.0).schluessel == "blender.exe"
    assert eintrag_fuer(YT, KiUrteil(Status.UNKLAR, "?", 0.3, "seite"), "k", 1.0) is None


def test_suche_reihenfolge():
    g = Gedaechtnis([GedaechtnisEintrag("k", "domain", "youtube.com", Status.ABGELENKT, "", 0.9, 0),
                     GedaechtnisEintrag("k", "seite", "youtube.com|Blender Donut", Status.FOKUS, "", 0.9, 0)])
    assert g.suche(YT).status is Status.FOKUS
    assert g.suche(pc(url="https://youtube.com/x", titel="Katzen")).status is Status.ABGELENKT
    assert g.suche(pc(url="https://example.org")) is None


def test_quelle_fuer():
    mk = lambda ebene, s: GedaechtnisEintrag("k", ebene, s, Status.FOKUS, "", 1, 0)
    assert quelle_fuer(mk("seite", "a|b")) == "seite:a|b"
    assert quelle_fuer(mk("domain", "a.com")) == "domain:a.com"
    assert quelle_fuer(mk("programm", "a.exe")) == "prozess:a.exe"
