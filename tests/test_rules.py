import pytest

from focusguard.decision.rules import domain_aus_url, domain_passt, programm_passt, regel_urteil
from focusguard.models import AufgabenListen, Status
from hilfen import pc, einst


@pytest.mark.parametrize("url,erwartet", [
    ("https://www.youtube.com/watch?v=1", "youtube.com"), ("youtube.com/watch?v=1", "youtube.com"),
    ("HTTP://Docs.Blender.org/manual", "docs.blender.org"), ("localhost:8080/x", "localhost"),
    ("chrome://newtab", None), ("", None), (None, None)])
def test_domain_aus_url(url, erwartet):
    assert domain_aus_url(url) == erwartet


def test_domain_und_programm_passt():
    assert domain_passt("docs.blender.org", ["blender.org"]) and domain_passt("blender.org", ["blender.org"])
    assert not domain_passt("notblender.org", ["blender.org"])
    assert programm_passt("Blender.EXE", ["blender.exe"]) and not programm_passt("blender2.exe", ["blender.exe"])


def test_regel_reihenfolge():
    g = einst().listen
    aufgabe = AufgabenListen(fokus_programme=("chrome.exe",), fokus_domains=("blender.org",))
    u = regel_urteil(pc(url="https://www.instagram.com/"), aufgabe, g)
    assert (u.status, u.quelle, u.herkunft) == (Status.ABGELENKT, "domain:instagram.com", "regel")
    assert regel_urteil(pc(url="https://docs.blender.org/x"), aufgabe, g).quelle == "domain:blender.org"
    assert regel_urteil(pc(url="https://example.org"), aufgabe, g).quelle == "prozess:chrome.exe"
    assert regel_urteil(pc("steam.exe"), AufgabenListen(), g).quelle == "prozess:steam.exe"
    assert regel_urteil(pc("notepad.exe"), AufgabenListen(), g) is None


def test_aufgaben_fokus_schlaegt_globale_ablenkung():
    u = regel_urteil(pc(url="https://instagram.com"), AufgabenListen(fokus_domains=("instagram.com",)), einst().listen)
    assert u.status is Status.FOKUS
