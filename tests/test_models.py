from focusguard.models import aufgabe_key, quelle_domain, quelle_prozess, quelle_seite, AufgabenListen, KiAnfrage, KiArt
from focusguard.clock import TestUhr


def test_aufgabe_key_normalisiert():
    assert aufgabe_key("  Blender   Grundlagen\tLernen ") == "blender grundlagen lernen"


def test_quellen_format():
    assert quelle_domain("instagram.com") == "domain:instagram.com"
    assert quelle_prozess("steam.exe") == "prozess:steam.exe"
    assert quelle_seite("youtube.com|Titel") == "seite:youtube.com|Titel"


def test_listen_ergaenzen_ohne_duplikate():
    l = AufgabenListen(fokus_domains=("blender.org",))
    assert l.mit_fokus_domain("blender.org").fokus_domains == ("blender.org",)
    assert l.mit_fokus_programm("blender.exe").fokus_programme == ("blender.exe",)
    assert AufgabenListen().ist_leer() and not l.ist_leer()


def test_prioritaet():
    p = lambda art: KiAnfrage(art, "q", 0.0, None, True, True).prioritaet
    assert p(KiArt.HANDY) < p(KiArt.SEITE) < p(KiArt.STICHPROBE)


def test_test_uhr():
    u = TestUhr(100.0)
    u.vor(2.5)
    assert u() == 102.5
