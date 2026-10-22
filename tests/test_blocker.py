from focusguard.blocker import sperr_aktion, Blocker
from focusguard.models import AufgabenListen
from focusguard.clock import TestUhr
from hilfen import pc

NIE = ("explorer.exe", "taskmgr.exe")


def test_sperr_aktionen():
    leer = AufgabenListen()
    assert sperr_aktion(pc(url="https://m.instagram.com/x"), {"domain:instagram.com"}, NIE, leer) == "tab_schliessen"
    assert sperr_aktion(pc("steam.exe"), {"prozess:steam.exe"}, NIE, leer) == "minimieren"
    assert sperr_aktion(pc(url="https://youtube.com/w", titel="Katzen"), {"seite:youtube.com|Katzen"}, NIE, leer) == "tab_schliessen"
    assert sperr_aktion(pc("game.exe", titel="Level 1"), {"seite:game.exe|Level 1"}, NIE, leer) == "minimieren"
    assert sperr_aktion(pc(url="https://example.org"), {"domain:instagram.com"}, NIE, leer) is None


def test_nie_sperren_und_fokus_vorrang():
    assert sperr_aktion(pc("explorer.exe"), {"prozess:explorer.exe"}, NIE, AufgabenListen()) is None
    assert sperr_aktion(pc(url="https://instagram.com"), {"domain:instagram.com"}, NIE,
                        AufgabenListen(fokus_domains=("instagram.com",))) is None


def blocker(uhr, vorne=1):
    log = []
    return Blocker(NIE, uhr, lambda h: log.append(("min", h)), lambda: log.append(("w",)), lambda: vorne), log


def test_blocker_cooldown_2_s():
    u = TestUhr(0)
    b, log = blocker(u)
    insta = pc(url="https://instagram.com", fenster_id=1)
    assert b.pruefe(insta, {"domain:instagram.com"}, AufgabenListen()) == "tab_schliessen"
    u.vor(1)
    assert b.pruefe(insta, {"domain:instagram.com"}, AufgabenListen()) is None
    u.vor(1.1)
    b.pruefe(insta, {"domain:instagram.com"}, AufgabenListen())
    assert log == [("w",), ("w",)]


def test_blocker_tab_nur_wenn_fenster_noch_vorne():
    b, log = blocker(TestUhr(0), vorne=2)
    assert b.pruefe(pc(url="https://instagram.com", fenster_id=1), {"domain:instagram.com"}, AufgabenListen()) is None
    assert log == []


def test_blocker_minimiert_fenster_und_faengt_fehler():
    b, log = blocker(TestUhr(0), vorne=5)
    b.pruefe(pc("steam.exe", fenster_id=5), {"prozess:steam.exe"}, AufgabenListen())
    assert log == [("min", 5)]

    def kaputt(h):
        raise OSError("Zugriff verweigert")

    b2 = Blocker(NIE, TestUhr(0), kaputt, lambda: None, lambda: 5)
    assert b2.pruefe(pc("steam.exe", fenster_id=5), {"prozess:steam.exe"}, AufgabenListen()) == "fehler"


def test_blocker_tab_nur_wenn_titel_noch_passt_und_ohne_shift_alt():
    log = []
    titel = {"t": "Fokus-Tab"}
    taste = {"an": False}
    b = Blocker(NIE, TestUhr(0), lambda h: None, lambda: log.append("w"), lambda: 1,
                titel=lambda h: titel["t"], modifikator=lambda: taste["an"])
    insta = pc(url="https://instagram.com", titel="Instagram", fenster_id=1)
    assert b.pruefe(insta, {"domain:instagram.com"}, AufgabenListen()) is None and log == []
    titel["t"] = "Instagram"
    taste["an"] = True
    assert b.pruefe(insta, {"domain:instagram.com"}, AufgabenListen()) is None and log == []
    taste["an"] = False
    assert b.pruefe(insta, {"domain:instagram.com"}, AufgabenListen()) == "tab_schliessen" and log == ["w"]
