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


def test_einstellungen_unter_windows_mit_notepad(tmp_path):
    from focusguard.app import oeffne_einstellungen
    aufrufe, urls = [], []
    pfad = tmp_path / "settings.toml"
    oeffne_einstellungen(pfad, "win32", starte=aufrufe.append, oeffne_url=urls.append)
    assert aufrufe == [["notepad.exe", str(pfad)]] and urls == []
    oeffne_einstellungen(pfad, "linux", starte=aufrufe.append, oeffne_url=urls.append)
    assert urls == [pfad]
