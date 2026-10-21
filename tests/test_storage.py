from focusguard.storage import Speicher
from focusguard.models import Session, GedaechtnisEintrag, AufgabenListen, Status


def test_session_anlegen_und_beenden():
    s = Speicher(":memory:")
    sid = s.neue_session(Session(None, "Blender", "blender", 1000.0, 50))
    s.beende_session(sid, 1600.0, True)
    [x] = s.sessions_seit(0)
    assert (x.id, x.ende, x.vorzeitig_beendet, x.geplant_min) == (sid, 1600.0, True, 50)


def test_ereignisse_reihenfolge_und_details():
    s = Speicher(":memory:")
    sid = s.neue_session(Session(None, "a", "a", 0.0, 25))
    s.ereignis(sid, 2.0, "eskalation", "domain:x.com", "abgelenkt", {"stufe": 2})
    s.ereignis(sid, 1.0, "statuswechsel", "", "fokus")
    e = s.ereignisse(sid)
    assert [x.art for x in e] == ["statuswechsel", "eskalation"] and e[1].details == {"stufe": 2} and e[0].details == {}


def test_gedaechtnis_upsert():
    s = Speicher(":memory:")
    e1 = GedaechtnisEintrag("k", "seite", "youtube.com|T", Status.FOKUS, "passt", 0.9, 1.0)
    s.speichere_gedaechtnis(e1)
    s.speichere_gedaechtnis(GedaechtnisEintrag("k", "seite", "youtube.com|T", Status.ABGELENKT, "nein", 0.8, 2.0))
    [x] = s.lade_gedaechtnis("k")
    assert x.status is Status.ABGELENKT and s.lade_gedaechtnis("anders") == []


def test_listen_ersetzen_und_leer():
    s = Speicher(":memory:")
    s.speichere_listen("k", AufgabenListen(("blender.exe",), ("blender.org",), (), ()))
    s.speichere_listen("k", AufgabenListen((), ("docs.blender.org",), (), ("9gag.com",)))
    assert s.lade_listen("k") == AufgabenListen((), ("docs.blender.org",), (), ("9gag.com",))
    assert s.lade_listen("neu") == AufgabenListen()


def test_datei_bleibt_erhalten(tmp_path):
    p = tmp_path / "fg.db"
    s = Speicher(p)
    s.neue_session(Session(None, "a", "a", 0.0, 25))
    s.schliesse()
    assert len(Speicher(p).sessions_seit(0)) == 1
