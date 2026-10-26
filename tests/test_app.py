import subprocess
import sys


def test_pruefen_meldet_fehlenden_schluessel(tmp_path):
    (tmp_path / "modelle").mkdir()
    for name in ("face_landmarker.task", "efficientdet_lite0.tflite"):   # avoid downloads in the test
        (tmp_path / "modelle" / name).write_bytes(b"x")
    env = {"FOCUSGUARD_HOME": str(tmp_path), "PATH": "", "QT_QPA_PLATFORM": "offscreen"}
    r = subprocess.run([sys.executable, "-m", "focusguard", "--pruefen"], capture_output=True, text=True, env=env,
                       timeout=120)
    assert "[FEHLT] ANTHROPIC_API_KEY gesetzt" in r.stdout and "[OK] Python >= 3.12" in r.stdout
    assert "[OK] Modelle vorhanden" in r.stdout and r.returncode == 1
    assert "[OK] FocusGuard-Module" in r.stdout


def test_einstellungen_unter_windows_mit_notepad(tmp_path):
    from focusguard.app import oeffne_einstellungen
    aufrufe, urls = [], []
    pfad = tmp_path / "settings.toml"
    oeffne_einstellungen(pfad, "win32", starte=aufrufe.append, oeffne_url=urls.append)
    assert aufrufe == [["notepad.exe", str(pfad)]] and urls == []
    oeffne_einstellungen(pfad, "linux", starte=aufrufe.append, oeffne_url=urls.append)
    assert urls == [pfad]


def test_version_text(tmp_path):
    import json
    from focusguard.app import version_text
    datei = tmp_path / "version.json"
    assert version_text(datei) == "Entwicklungsstand"
    datei.write_text(json.dumps({"sha": "abc1234def" + "0" * 30, "nachricht": "Neue Funktion"}))
    assert version_text(datei) == "abc1234 – Neue Funktion"


def test_api_schluessel_notfalls_aus_registry():
    from focusguard.app import uebernimm_api_schluessel
    registry = lambda: "sk-ant-aus-registry"
    umgebung = {}
    uebernimm_api_schluessel(umgebung, "win32", registry)
    assert umgebung == {"ANTHROPIC_API_KEY": "sk-ant-aus-registry"}
    umgebung = {"ANTHROPIC_API_KEY": "sk-ant-gesetzt"}
    uebernimm_api_schluessel(umgebung, "win32", registry)
    assert umgebung == {"ANTHROPIC_API_KEY": "sk-ant-gesetzt"}
    umgebung = {}
    uebernimm_api_schluessel(umgebung, "linux", registry)
    uebernimm_api_schluessel(umgebung, "win32", lambda: None)
    assert umgebung == {}


def test_main_uebernimmt_schluessel_vor_dem_start(monkeypatch):
    import focusguard.app as app
    aufrufe = []
    monkeypatch.setattr(app, "uebernimm_api_schluessel", lambda: aufrufe.append("schluessel"))
    monkeypatch.setattr(app, "importtest", lambda: aufrufe.append("importtest") or 0)
    assert app.main(["--importtest"]) == 0 and aufrufe == ["schluessel", "importtest"]


def test_importtest_laedt_alle_module():
    r = subprocess.run([sys.executable, "-m", "focusguard", "--importtest"], capture_output=True, text=True,
                       env={"PATH": "", "QT_QPA_PLATFORM": "offscreen"}, timeout=120)
    assert r.returncode == 0, r.stderr
