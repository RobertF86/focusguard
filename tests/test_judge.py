from focusguard.decision.judge import Entscheider
from focusguard.decision.memory import Gedaechtnis
from focusguard.models import (AufgabenListen, KiArt, KiErgebnis, KiUrteil, Status,
                               WebcamBeobachtung as W)
from hilfen import pc, einst


def ent(**kw):
    return Entscheider(einst(**kw), "blender", AufgabenListen(fokus_programme=("blender.exe",)), Gedaechtnis(), 0.0)


def ki(e, anfrage, status, t, sicherheit=0.9, gilt="seite"):
    return e.ki_ergebnis(KiErgebnis(anfrage, KiUrteil(status, "Grund", sicherheit, gilt), None, 100, 10), t)


def test_ohne_beobachtungen_fokus():
    assert ent().urteil(1).status is Status.FOKUS


def test_regel_ablenkung():
    e = ent()
    e.pc(pc(url="https://instagram.com", zeit=1))
    assert e.urteil(1).quelle == "domain:instagram.com"


def test_unbekannte_seite_genau_eine_anfrage_und_gedaechtnis():
    e = ent()
    e.pc(pc(url="https://example.org", titel="T", zeit=1))
    assert e.urteil(1).status is Status.UNKLAR
    [a] = e.ki_anfragen(1)
    assert (a.art, a.quelle, a.mit_bildschirm) == (KiArt.SEITE, "seite:example.org|T", True)
    e.pc(pc(url="https://example.org", titel="T", zeit=2))
    assert e.ki_anfragen(2) == []
    eintrag = ki(e, a, Status.ABGELENKT, 3)
    assert eintrag.schluessel == "example.org|T"
    u = e.urteil(3)
    assert (u.status, u.herkunft) == (Status.ABGELENKT, "gedaechtnis")


def test_ki_fehler_erneut_frueh_nach_30_s():
    e = ent()
    e.pc(pc(url="https://example.org", titel="T", zeit=1))
    [a] = e.ki_anfragen(1)
    assert e.ki_ergebnis(KiErgebnis(a, None, "Netz weg", 0, 0), 2) is None
    for t in (20, 31):
        e.pc(pc(url="https://example.org", titel="T", zeit=t))
    assert e.urteil(31).status is Status.UNKLAR
    assert e.ki_anfragen(31) == [] and len(e.ki_anfragen(32.5)) == 1


def test_ki_unklar_erneut_nach_300_s():
    e = ent()
    e.pc(pc(url="https://example.org", zeit=1))
    [a] = e.ki_anfragen(1)
    assert ki(e, a, Status.UNKLAR, 2) is None
    seiten = lambda t: [x for x in e.ki_anfragen(t) if x.art is KiArt.SEITE]   # Stichproben are due too
    e.pc(pc(url="https://example.org", zeit=290))
    assert seiten(290) == []
    e.pc(pc(url="https://example.org", zeit=303))
    assert len(seiten(303)) == 1


def test_pc_veraltet_und_pc_aus():
    e = ent()
    e.pc(pc(url="https://instagram.com", zeit=1))
    assert e.urteil(7).status is Status.FOKUS
    e.pc(pc(url="https://instagram.com", zeit=8))
    e.setze_sensoren(False, True, True)
    assert e.urteil(8).status is Status.FOKUS


def test_abgelenkt_schlaegt_abwesend():
    e = ent()
    e.webcam(W(0, True, 5))
    for t in range(1, 20):
        e.webcam(W(t, False, None))
    e.pc(pc(url="https://netflix.com", zeit=19))
    assert e.urteil(19).status is Status.ABGELENKT


def test_stichprobe_alle_120_s_mit_bestaetigung():
    e = ent()
    e.pc(pc("blender.exe", zeit=119))
    assert e.ki_anfragen(119) == []
    [a] = e.ki_anfragen(120)
    assert a.art is KiArt.STICHPROBE and a.mit_bildschirm and a.mit_webcam
    ki(e, a, Status.ABGELENKT, 125)
    e.pc(pc("blender.exe", zeit=150))
    assert e.urteil(150).status is Status.FOKUS
    assert e.ki_anfragen(150) == []
    e.pc(pc("blender.exe", zeit=155))
    [b] = e.ki_anfragen(155)
    ki(e, b, Status.ABGELENKT, 156)
    u = e.urteil(156)
    assert (u.status, u.quelle, u.seit) == (Status.ABGELENKT, "stichprobe", 156)   # zählt ab der Bestätigung
    [c] = stichproben(e, 186)
    ki(e, c, Status.ABGELENKT, 187)
    assert e.urteil(187).seit == 156


def test_stichprobe_nachpruefung_negativ():
    e = ent()
    [a] = e.ki_anfragen(120)
    ki(e, a, Status.ABGELENKT, 121)
    [b] = e.ki_anfragen(151)
    ki(e, b, Status.FOKUS, 152)
    assert e.ki_anfragen(271) == [] and len(e.ki_anfragen(272)) == 1


def test_keine_stichprobe_bei_abwesend():
    e = ent()
    e.webcam(W(0, True, 5))
    for t in range(1, 121):
        e.webcam(W(t, False, None))
    assert [a for a in e.ki_anfragen(120) if a.art is KiArt.STICHPROBE] == []


def test_korrekturen():
    e = ent()
    e.pc(pc(url="https://instagram.com", zeit=1))
    listen, eintrag = e.korrektur("domain:instagram.com", 1)
    assert "instagram.com" in listen.fokus_domains and eintrag is None
    assert e.urteil(1).status is Status.FOKUS
    listen, eintrag = e.korrektur("seite:example.org|T", 2)
    assert listen is None and (eintrag.ebene, eintrag.status) == ("seite", Status.FOKUS)
    assert e.korrektur("handy", 3) == (None, None)


def _bestaetigte_stichprobe():
    e = ent()
    e.pc(pc("blender.exe", zeit=119))
    [a] = e.ki_anfragen(120)
    ki(e, a, Status.ABGELENKT, 125)
    e.pc(pc("blender.exe", zeit=155))
    [b] = e.ki_anfragen(155)
    ki(e, b, Status.ABGELENKT, 156)
    return e


def test_stichprobe_fehler_beendet_bestaetigung():
    e = _bestaetigte_stichprobe()
    e.pc(pc("blender.exe", zeit=186))
    [c] = e.ki_anfragen(186)
    e.ki_ergebnis(KiErgebnis(c, None, "Netz weg"), 187)
    assert e.urteil(187).status is Status.FOKUS


def test_stichprobe_bestaetigung_laeuft_ab():
    e = _bestaetigte_stichprobe()
    e.pc(pc("blender.exe", zeit=200))
    assert e.urteil(200).quelle == "stichprobe"
    e.pc(pc("blender.exe", zeit=217))
    assert e.urteil(217).status is Status.FOKUS


def test_programm_wird_nach_15_minuten_neu_beurteilt():
    e = ent()
    e.pc(pc("claude.exe", titel="Claude", zeit=1))
    [a] = e.ki_anfragen(1)
    ki(e, a, Status.ABGELENKT, 2, gilt="programm")
    e.pc(pc("claude.exe", titel="Claude", zeit=902))
    assert e.urteil(902).status is Status.ABGELENKT
    e.pc(pc("claude.exe", titel="Claude", zeit=903))
    assert e.urteil(903).status is Status.UNKLAR
    assert [x.quelle for x in e.ki_anfragen(903) if x.art is KiArt.SEITE] == ["seite:claude.exe|Claude"]


def test_neutrales_fenster_ueberbrueckt_nur_kurz():
    e = ent()
    e.pc(pc(url="https://instagram.com", zeit=1))
    e.pc(pc("explorer.exe", titel="Task Switching", zeit=2))
    assert e.urteil(2).quelle == "domain:instagram.com"          # kurzes Alt+Tab ändert nichts
    for t in range(3, 121):                                       # Fenster minimiert oder geschlossen: Desktop vorne
        e.pc(pc("explorer.exe", titel="Program Manager", zeit=t))
    u = e.urteil(120)
    assert (u.status, u.herkunft) == (Status.UNKLAR, "neutral")
    assert [a for a in e.ki_anfragen(120) if a.art is KiArt.SEITE] == []


def test_neutrales_fenster_ohne_vorheriges_urteil():
    e = ent()
    e.pc(pc("explorer.exe", titel="", zeit=1))
    u = e.urteil(1)
    assert (u.status, u.herkunft) == (Status.UNKLAR, "neutral") and e.ki_anfragen(1) == []


def test_neutrales_fenster_ist_das_aktuelle_fenster():
    e = ent()
    e.pc(pc(url="https://example.org", titel="T", zeit=1))
    e.pc(pc("startmenuexperiencehost.exe", titel="Start", zeit=2))
    assert e.letzte_pc.prozess == "startmenuexperiencehost.exe"    # für die Prüfung „Seite nicht mehr aktiv“


def test_keine_seiten_anfrage_waehrend_neutrales_fenster_vorne():
    e = ent()
    e.pc(pc(url="https://example.org", titel="T", zeit=1))
    [a] = e.ki_anfragen(1)
    e.ki_ergebnis(KiErgebnis(a, None, "Netz weg", 0, 0), 2)       # nächster Versuch ab 32 s
    e.pc(pc(url="https://example.org", titel="T", zeit=31))
    e.pc(pc("explorer.exe", titel="", zeit=32))
    assert e.ki_anfragen(33) == []
    e.pc(pc(url="https://example.org", titel="T", zeit=34))
    assert len(e.ki_anfragen(34)) == 1


def test_gesperrter_bildschirm_mit_webcam_gilt_als_abwesend():
    e = ent()
    e.webcam(W(0, True, 5))
    e.pc(pc(url="https://instagram.com", zeit=1))
    for t in range(1, 21):
        e.webcam(W(t, False, None))
        e.pc(pc("lockapp.exe", titel="Sperrbildschirm", zeit=t + 0.5))
    assert e.urteil(20).status is Status.ABWESEND


def stichproben(e, t):
    return [a for a in e.ki_anfragen(t) if a.art is KiArt.STICHPROBE]


def test_stichprobe_zuruecksetzen_beendet_ablenkung_und_wartet_normal():
    e = _bestaetigte_stichprobe()
    e.stichprobe_zuruecksetzen(160)
    e.pc(pc("blender.exe", zeit=160))
    assert e.urteil(160).status is Status.FOKUS
    assert stichproben(e, 279) == [] and len(stichproben(e, 280)) == 1


def test_stichprobe_von_vor_dem_zuruecksetzen_wird_verworfen():
    e = _bestaetigte_stichprobe()
    [c] = stichproben(e, 186)
    e.stichprobe_zuruecksetzen(190)
    ki(e, c, Status.ABGELENKT, 191)
    e.pc(pc("blender.exe", zeit=192))
    assert e.urteil(192).status is Status.FOKUS
    assert stichproben(e, 309) == [] and len(stichproben(e, 310)) == 1
