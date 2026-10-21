import pytest

from focusguard.config import lade_einstellungen, setze_sensor, datenordner, EinstellungsFehler


def test_fehlende_datei_wird_mit_standardwerten_angelegt(tmp_path):
    p = tmp_path / "settings.toml"
    e = lade_einstellungen(p)
    assert p.exists()
    assert e.ki.modell == "claude-haiku-5-5" and e.ki.max_aufrufe_pro_minute == 2
    assert (e.eskalation.stufe1_sekunden, e.eskalation.stufe2_sekunden, e.eskalation.stufe3_sekunden) == (10, 40, 70)
    assert e.ki.stichprobe_sekunden == 120 and e.ki.stichprobe_nachpruefung_sekunden == 30
    assert e.erkennung.kopf_gesenkt_grad == 20 and e.erkennung.abwesend_nach_sekunden == 15
    assert "instagram.com" in e.listen.ablenkung_domains
    assert e.listen.nie_sperren == ("explorer.exe", "taskmgr.exe", "python.exe", "pythonw.exe")


def test_teilweise_datei_ergaenzt_standardwerte(tmp_path):
    p = tmp_path / "settings.toml"
    p.write_text("[eskalation]\nstufe1_sekunden = 5\nunbekannt = 1\n")
    e = lade_einstellungen(p)
    assert e.eskalation.stufe1_sekunden == 5 and e.eskalation.stufe2_sekunden == 40 and e.sensoren.pc is True


def test_ungueltiges_toml_wirft(tmp_path):
    p = tmp_path / "settings.toml"
    p.write_text("[ki\nmodell = ")
    with pytest.raises(EinstellungsFehler):
        lade_einstellungen(p)


def test_falscher_typ_nennt_schluessel(tmp_path):
    p = tmp_path / "settings.toml"
    p.write_text('[eskalation]\nstufe1_sekunden = "zehn"\n')
    with pytest.raises(EinstellungsFehler, match="stufe1_sekunden"):
        lade_einstellungen(p)


def test_setze_sensor_aendert_nur_diese_zeile(tmp_path):
    p = tmp_path / "settings.toml"
    lade_einstellungen(p)
    setze_sensor(p, "webcam", False)
    text = p.read_text()
    assert "webcam = false" in text and "# zugleich die Gnadenfrist" in text
    assert lade_einstellungen(p).sensoren.webcam is False


def test_datenordner_focusguard_home(monkeypatch, tmp_path):
    monkeypatch.setenv("FOCUSGUARD_HOME", str(tmp_path / "fg"))
    assert datenordner() == tmp_path / "fg" and (tmp_path / "fg").is_dir()
