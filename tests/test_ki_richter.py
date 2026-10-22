import json
import types

import pytest

from focusguard.ai.client import KiRichter, Ratenbegrenzer, KiRohAntwort, KiFehler, anthropic_sender
from focusguard.clock import TestUhr
from focusguard.models import KiAnfrage, KiArt, Status
from hilfen import pc

ANTWORT = json.dumps({"status": "fokus", "begruendung": "passt", "sicherheit": 0.9, "gilt_fuer": "seite"})


class FakeSender:
    def __init__(self, text=ANTWORT, fehler=None):
        self.aufrufe, self.text, self.fehler = [], text, fehler

    def __call__(self, kwargs):
        self.aufrufe.append(kwargs)
        if self.fehler:
            raise self.fehler
        return KiRohAntwort(self.text, 1200, 40)


class FakeBilder:
    def __init__(self, cam=b"cam", monitor_fehler=False):
        self.cam, self.mf = cam, monitor_fehler

    def aktiver_monitor(self, fid):
        if self.mf:
            raise OSError("kein Monitor")
        return b"mon"

    def alle_monitore(self):
        return [b"m1", b"m2"]

    def webcam(self):
        return self.cam


def anfrage(art=KiArt.SEITE, quelle="seite:a|b", **kw):
    return KiAnfrage(art, quelle, 0.0, kw.get("pc", pc(url="https://a.org", titel="b")), kw.get("bs", True),
                     kw.get("wc", False))


def richter(sender=None, bilder=None, uhr=None, ablage=None):
    return KiRichter(sender or FakeSender(), bilder or FakeBilder(), "claude-haiku-5-5", 0.6, 2, uhr or TestUhr(0), ablage)


def bilder_typen(kwargs):
    return [b["type"] for b in kwargs["messages"][0]["content"]]


def test_ratenbegrenzer():
    u = TestUhr(0)
    r = Ratenbegrenzer(2, u)
    assert r.versuche() and r.versuche() and not r.versuche()
    u.vor(30)
    assert r.versuche() and not r.versuche()


def test_reihenfolge_und_duplikate():
    s = FakeSender()
    r = richter(s)
    assert r.verarbeite_naechste() is None
    r.einreihen(anfrage(KiArt.STICHPROBE, "stichprobe"), "a")
    r.einreihen(anfrage(), "a")
    r.einreihen(anfrage(), "a")
    r.einreihen(anfrage(KiArt.HANDY, "handy", bs=False, wc=True), "a")
    arten = [r.verarbeite_naechste().anfrage.art for _ in range(2)]
    assert arten == [KiArt.HANDY, KiArt.SEITE] and r.verarbeite_naechste() is None   # rate limit
    assert len(s.aufrufe) == 2


def test_ergebnis_mit_tokens_und_bild():
    s = FakeSender()
    r = richter(s)
    r.einreihen(anfrage(), "Blender")
    e = r.verarbeite_naechste()
    assert e.urteil.status is Status.FOKUS and (e.tokens_ein, e.tokens_aus) == (1200, 40) and e.fehler is None
    assert bilder_typen(s.aufrufe[0]) == ["image", "text"]


def test_fehler_ergeben_ergebnis_ohne_urteil():
    r = richter(FakeSender(fehler=KiFehler("Netz weg")))
    r.einreihen(anfrage(), "a")
    e = r.verarbeite_naechste()
    assert e.urteil is None and "Netz weg" in e.fehler
    r = richter(FakeSender(text="kaputt"))
    r.einreihen(anfrage(), "a")
    assert r.verarbeite_naechste().urteil is None


def test_handy_ohne_webcam_bild_ohne_aufruf():
    s = FakeSender()
    r = richter(s, FakeBilder(cam=None))
    r.einreihen(anfrage(KiArt.HANDY, "handy", bs=False, wc=True), "a")
    assert r.verarbeite_naechste().fehler == "Kein Webcam-Bild" and s.aufrufe == []


def test_monitorfehler_seite_nur_text():
    s = FakeSender()
    r = richter(s, FakeBilder(monitor_fehler=True))
    r.einreihen(anfrage(), "a")
    r.verarbeite_naechste()
    assert bilder_typen(s.aufrufe[0]) == ["text"]


def test_stichprobe_bilder():
    s = FakeSender()
    r = richter(s)
    r.einreihen(anfrage(KiArt.STICHPROBE, "stichprobe", wc=True), "a")
    r.verarbeite_naechste()
    assert bilder_typen(s.aufrufe[0]) == ["image", "image", "image", "text"]


def test_ablage(tmp_path):
    r = richter(ablage=tmp_path)
    r.einreihen(anfrage(), "a")
    r.verarbeite_naechste()
    assert len(list(tmp_path.glob("*.jpg"))) == 1 and len(list(tmp_path.glob("*.json"))) == 1


def test_startlisten_und_leeren():
    text = json.dumps({"fokus_programme": ["blender.exe"], "fokus_domains": [], "ablenkung_programme": [],
                       "ablenkung_domains": []})
    r = richter(FakeSender(text=text))
    for _ in range(5):
        assert r.startlisten("Blender").fokus_programme == ("blender.exe",)
    assert richter(FakeSender(fehler=KiFehler("x"))).startlisten("a") is None
    r2 = richter()
    r2.einreihen(anfrage(), "a")
    r2.leeren()
    assert r2.verarbeite_naechste() is None


def test_anthropic_sender_refusal_und_max_tokens():
    def client(stop, bloecke):
        antwort = types.SimpleNamespace(stop_reason=stop, content=bloecke,
                                        usage=types.SimpleNamespace(input_tokens=5, output_tokens=2))
        return types.SimpleNamespace(messages=types.SimpleNamespace(create=lambda **kw: antwort))

    text = [types.SimpleNamespace(type="text", text=ANTWORT)]
    assert anthropic_sender(client("end_turn", text))({}).text == ANTWORT
    for stop, bloecke in (("refusal", text), ("max_tokens", text), ("end_turn", [])):
        with pytest.raises(KiFehler):
            anthropic_sender(client(stop, bloecke))({})


def test_bildschirm_pause_haelt_seite_und_stichprobe():
    s = FakeSender()
    r = richter(s)
    r.setze_bildschirm_pause(True)
    r.einreihen(anfrage(), "a")
    r.einreihen(anfrage(KiArt.STICHPROBE, "stichprobe", wc=True), "a")
    assert r.verarbeite_naechste() is None and s.aufrufe == []
    r.einreihen(anfrage(KiArt.HANDY, "handy", bs=False, wc=True), "a")
    assert r.verarbeite_naechste().anfrage.art is KiArt.HANDY
    r.setze_bildschirm_pause(False)
    assert r.verarbeite_naechste().anfrage.art is KiArt.SEITE


def test_veraltete_seite_wird_verworfen_ohne_aufruf():
    s = FakeSender()
    r = KiRichter(s, FakeBilder(), "claude-haiku-5-5", 0.6, 2, TestUhr(0),
                  aktuelle_pc=lambda: pc(url="https://b.org", titel="anders"))
    r.einreihen(anfrage(), "a")
    e = r.verarbeite_naechste()
    assert e.urteil is None and e.fehler == "Seite nicht mehr aktiv" and s.aufrufe == []
    r.einreihen(anfrage(KiArt.HANDY, "handy", bs=False, wc=True), "a")
    r.einreihen(anfrage(KiArt.STICHPROBE, "stichprobe", wc=True), "a")
    assert r.verarbeite_naechste() is not None and r.verarbeite_naechste() is not None   # no rate slot used
