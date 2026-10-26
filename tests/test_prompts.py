import base64
import json

import pytest

from focusguard.ai.prompts import (parse_urteil, parse_startlisten, KiAntwortFehler, seite_inhalt,
                                   stichprobe_inhalt, baue_anfrage, SYSTEM_URTEIL, URTEIL_SCHEMA)
from focusguard.models import Status
from hilfen import pc


def j(**kw):
    d = {"status": "abgelenkt", "begruendung": "Instagram", "sicherheit": 0.9, "gilt_fuer": "domain"}
    d.update(kw)
    return json.dumps(d)


def test_parse_urteil_gueltig_und_grenzen():
    u = parse_urteil(j(), 0.6)
    assert (u.status, u.begruendung, u.sicherheit, u.gilt_fuer) == (Status.ABGELENKT, "Instagram", 0.9, "domain")
    assert parse_urteil(j(sicherheit=0.5), 0.6).status is Status.UNKLAR
    assert parse_urteil(j(sicherheit=1.7), 0.6).sicherheit == 1.0


@pytest.mark.parametrize("text", ["", "kein json", "[]", '{"status": "fokus"}', j(status="weiss nicht"),
                                  j(gilt_fuer="alles")])
def test_parse_urteil_ungueltig_wirft(text):
    with pytest.raises(KiAntwortFehler):
        parse_urteil(text, 0.6)


def test_parse_startlisten_normalisiert_und_filtert():
    l = parse_startlisten(json.dumps({"fokus_programme": [" Blender.EXE "],
                                      "fokus_domains": ["WWW.Blender.org", "youtube.com", "google.de"],
                                      "ablenkung_programme": [], "ablenkung_domains": ["https://www.9gag.com/hot"]}))
    assert l.fokus_programme == ("blender.exe",) and l.fokus_domains == ("blender.org",)
    assert l.ablenkung_domains == ("9gag.com",)


def test_seite_inhalt():
    inhalt = seite_inhalt("Blender lernen", pc(url="https://example.org/x", titel="T"), b"\xff\xd8jpg")
    assert inhalt[0]["type"] == "image" and base64.b64decode(inhalt[0]["source"]["data"]) == b"\xff\xd8jpg"
    assert all(s in inhalt[1]["text"] for s in ("Blender lernen", "chrome.exe", "T", "https://example.org/x"))
    assert [b["type"] for b in seite_inhalt("a", pc(), None)] == ["text"]


def test_stichprobe_inhalt():
    inhalt = stichprobe_inhalt("a", None, [b"m1", b"m2"], b"cam")
    assert [b["type"] for b in inhalt] == ["image", "image", "image", "text"]
    assert all(s in inhalt[-1]["text"] for s in ("Monitor 1", "Monitor 2", "Webcam"))


def test_stichprobe_zaehlt_andere_monitore_nur_bei_laufenden_medien():
    text = stichprobe_inhalt("a", pc("blender.exe", titel="Blender"), [b"m1", b"m2"], None)[-1]["text"]
    assert "blender.exe" in text
    regel = text.lower()
    assert "aktiven fenster" in regel and "andere monitore" in regel and "video" in regel
    assert "keine ablenkung" in regel


def test_baue_anfrage_ohne_sampling():
    k = baue_anfrage("claude-haiku-5-5", SYSTEM_URTEIL, [{"type": "text", "text": "x"}], URTEIL_SCHEMA)
    assert set(k) == {"model", "max_tokens", "system", "messages", "output_config"}
    assert k["model"] == "claude-haiku-5-5" and k["output_config"]["effort"] == "low"
    assert k["output_config"]["format"]["type"] == "json_schema"
