from focusguard.decision.memory import seiten_schluessel, eintrag_fuer, quelle_fuer, Gedaechtnis
from focusguard.models import KiUrteil, Status, GedaechtnisEintrag
from hilfen import pc

YT = pc(url="https://youtube.com/watch?v=1", titel="Blender Donut")


def test_seiten_schluessel():
    assert seiten_schluessel(YT) == "youtube.com|Blender Donut"
    assert seiten_schluessel(pc("blender.exe", titel="x")) == "blender.exe|x"


def test_eintrag_ebenen():
    docs = pc(url="https://docs.blender.org/x", titel="T")
    assert eintrag_fuer(docs, KiUrteil(Status.FOKUS, "ok", 0.9, "domain"), "k", 1.0).schluessel == "docs.blender.org"
    assert eintrag_fuer(pc("firefox.exe", titel="T"), KiUrteil(Status.FOKUS, "ok", 0.9, "domain"), "k", 1.0).ebene == "seite"
    assert eintrag_fuer(YT, KiUrteil(Status.FOKUS, "ok", 0.9, "programm"), "k", 1.0).ebene == "seite"
    assert eintrag_fuer(YT, KiUrteil(Status.UNKLAR, "?", 0.3, "seite"), "k", 1.0) is None


def test_ki_urteil_gilt_nie_fuer_ein_ganzes_programm():
    e = eintrag_fuer(pc("claude.exe", titel="Claude"), KiUrteil(Status.ABGELENKT, "Gitarren-App", 0.85, "programm"),
                     "k", 1.0)
    assert (e.ebene, e.schluessel) == ("seite", "claude.exe|Claude")
    assert eintrag_fuer(YT, KiUrteil(Status.FOKUS, "sicher", 1.0, "seite"), "k", 1.0).sicherheit < 1.0


def test_suche_ignoriert_alte_programm_eintraege():
    g = Gedaechtnis([GedaechtnisEintrag("k", "programm", "claude.exe", Status.ABGELENKT, "", 0.85, 0)])
    assert g.suche(pc("claude.exe", titel="Claude"), 1) is None


def test_ki_urteil_ueber_programm_laeuft_nach_15_minuten_ab():
    claude = pc("claude.exe", titel="Claude")
    g = Gedaechtnis([GedaechtnisEintrag("k", "seite", "claude.exe|Claude", Status.ABGELENKT, "", 0.85, 0)])
    assert g.suche(claude, 900) is not None and g.suche(claude, 901) is None
    korrigiert = Gedaechtnis([GedaechtnisEintrag("k", "seite", "claude.exe|Claude", Status.FOKUS, "", 1.0, 0)])
    assert korrigiert.suche(claude, 100_000) is not None                  # deine Korrektur läuft nie ab
    seite = Gedaechtnis([GedaechtnisEintrag("k", "seite", "youtube.com|Blender Donut", Status.FOKUS, "", 0.9, 0)])
    assert seite.suche(YT, 100_000) is not None                           # Browser-Seiten laufen nicht ab


def test_suche_reihenfolge():
    g = Gedaechtnis([GedaechtnisEintrag("k", "domain", "youtube.com", Status.ABGELENKT, "", 0.9, 0),
                     GedaechtnisEintrag("k", "seite", "youtube.com|Blender Donut", Status.FOKUS, "", 0.9, 0)])
    assert g.suche(YT, 1).status is Status.FOKUS
    assert g.suche(pc(url="https://youtube.com/x", titel="Katzen"), 1).status is Status.ABGELENKT
    assert g.suche(pc(url="https://example.org"), 1) is None


def test_quelle_fuer():
    mk = lambda ebene, s: GedaechtnisEintrag("k", ebene, s, Status.FOKUS, "", 1, 0)
    assert quelle_fuer(mk("seite", "a|b")) == "seite:a|b"
    assert quelle_fuer(mk("domain", "a.com")) == "domain:a.com"
    assert quelle_fuer(mk("programm", "a.exe")) == "prozess:a.exe"


def test_misch_plattform_nie_auf_domain_ebene():
    u = KiUrteil(Status.ABGELENKT, "Suche", 0.9, "domain")
    assert eintrag_fuer(YT, u, "k", 1.0).ebene == "seite"
    assert eintrag_fuer(pc(url="https://news.google.de/x", titel="T"), u, "k", 1.0).ebene == "seite"
    assert eintrag_fuer(pc(url="https://docs.blender.org/x", titel="T"), u, "k", 1.0).ebene == "domain"
