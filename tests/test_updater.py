import io
import json
import zipfile

import pytest

import updater
from updater import (Konfig, Stand, UpdateFehler, entpacke_unterordner, lade_konfig, lade_version, laeuft,
                     neuester_stand, pruefe_und_aktualisiere, speichere_konfig, tausche_ein, venv_python,
                     verknuepfungen_befehl, wende_an, wurzel_aus)

SHA = "a" * 40


def zip_mit(dateien: dict[str, bytes], oben="ScriptCollection-" + SHA) -> bytes:
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        z.writestr(oben + "/", b"")
        for name, inhalt in dateien.items():
            z.writestr(f"{oben}/{name}", inhalt)
    return puffer.getvalue()


APP_ZIP = zip_mit({"FocusGuard/pyproject.toml": b"[project]\nname='focusguard'\n",
                   "FocusGuard/focusguard/__init__.py": b"",
                   "FocusGuard/updater.py": b"# neuer updater\n",
                   "FocusGuard/README.md": b"neu",
                   "MaxScripts/anderes.ms": b"gehoert nicht dazu"})


class Befehle:
    def __init__(self, fehler_bei=None):
        self.liste, self.fehler_bei = [], fehler_bei

    def __call__(self, befehl):
        self.liste.append([str(t) for t in befehl])
        if self.fehler_bei and self.fehler_bei in " ".join(self.liste[-1]):
            raise UpdateFehler("Befehl fehlgeschlagen")


def api_antwort(sha=SHA, nachricht="Neue Funktion\n\nDetails"):
    return lambda url, timeout: {"sha": sha, "commit": {"message": nachricht}}


def test_konfig_standard_und_speichern(tmp_path):
    k = lade_konfig(tmp_path)
    assert (k.repo, k.branch, k.unterordner) == ("RobertF86/ScriptCollection", "claude/serene-hamilton-sjzb16", "FocusGuard")
    speichere_konfig(tmp_path, Konfig(k.repo, "master", k.unterordner))
    assert lade_konfig(tmp_path).branch == "master"
    (tmp_path / "update.json").write_text("kaputt")
    assert lade_konfig(tmp_path).branch == "claude/serene-hamilton-sjzb16"


def test_neuester_stand_kodiert_branch_und_kuerzt_nachricht():
    urls = []

    def holen(url, timeout):
        urls.append(url)
        return {"sha": SHA, "commit": {"message": "Erste Zeile\n\nRest"}}

    s = neuester_stand(lade_konfig_standard(), holen)
    assert s == Stand(SHA, "Erste Zeile")
    assert urls == ["https://api.github.com/repos/RobertF86/ScriptCollection/commits/claude%2Fserene-hamilton-sjzb16"]


def lade_konfig_standard():
    return Konfig("RobertF86/ScriptCollection", "claude/serene-hamilton-sjzb16", "FocusGuard")


def test_entpackt_nur_den_unterordner(tmp_path):
    ziel = tmp_path / "app.neu"
    entpacke_unterordner(APP_ZIP, "FocusGuard", ziel)
    assert (ziel / "pyproject.toml").exists() and (ziel / "focusguard" / "__init__.py").exists()
    assert not (ziel / "MaxScripts").exists() and not (ziel / "FocusGuard").exists()


def test_entpacken_wehrt_pfade_ausserhalb_ab(tmp_path):
    boese = zip_mit({"FocusGuard/pyproject.toml": b"x", "FocusGuard/../../boese.txt": b"x"})
    with pytest.raises(UpdateFehler):
        entpacke_unterordner(boese, "FocusGuard", tmp_path / "app.neu")
    assert not (tmp_path / "boese.txt").exists()


def test_entpacken_ohne_projekt_ist_fehler(tmp_path):
    with pytest.raises(UpdateFehler):
        entpacke_unterordner(zip_mit({"Anderes/x.txt": b"x"}), "FocusGuard", tmp_path / "app.neu")


def test_tausche_ein_ersetzt_app_und_raeumt_auf(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "alt.txt").write_text("alt")
    (tmp_path / "app.neu").mkdir()
    (tmp_path / "app.neu" / "neu.txt").write_text("neu")
    (tmp_path / "app.alt").mkdir()                       # Rest eines früheren Updates
    tausche_ein(tmp_path)
    assert (tmp_path / "app" / "neu.txt").exists() and not (tmp_path / "app" / "alt.txt").exists()
    assert not (tmp_path / "app.neu").exists() and not (tmp_path / "app.alt").exists()


def test_wende_an_erstinstallation(tmp_path):
    b = Befehle()
    pip = wende_an(tmp_path, lade_konfig_standard(), Stand(SHA, "Neu"), lambda url, timeout: APP_ZIP, b, "/usr/bin/python3")
    assert pip is True
    vpy = str(venv_python(tmp_path))
    assert b.liste[0] == ["/usr/bin/python3", "-m", "venv", str(tmp_path / ".venv")]
    assert b.liste[1] == [vpy, "-m", "pip", "install", "-e", str(tmp_path / "app")]
    assert (tmp_path / "updater.py").read_text() == "# neuer updater\n"
    v = lade_version(tmp_path)
    assert v["sha"] == SHA and v["nachricht"] == "Neu" and v["pyproject"]


def test_wende_an_ohne_neue_abhaengigkeiten_kein_pip(tmp_path):
    wende_an(tmp_path, lade_konfig_standard(), Stand(SHA, "x"), lambda url, timeout: APP_ZIP, Befehle(), "py")
    venv_python(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    venv_python(tmp_path).write_text("")
    b = Befehle()
    assert wende_an(tmp_path, lade_konfig_standard(), Stand("b" * 40, "y"), lambda url, timeout: APP_ZIP, b, "py") is False
    assert b.liste == [] and lade_version(tmp_path)["sha"] == "b" * 40


def test_pip_fehler_speichert_keine_version(tmp_path):
    with pytest.raises(UpdateFehler):
        wende_an(tmp_path, lade_konfig_standard(), Stand(SHA, "x"), lambda url, timeout: APP_ZIP, Befehle("pip"), "py")
    assert lade_version(tmp_path) == {}            # beim nächsten Start wird es erneut versucht


def test_pruefe_und_aktualisiere(tmp_path):
    ausgaben = []
    lade = lambda url, timeout: APP_ZIP
    assert pruefe_und_aktualisiere(tmp_path, api_antwort(), lade, Befehle(), "py", ausgaben.append) == "aktualisiert"
    assert any("Neue Funktion" in a for a in ausgaben)
    assert pruefe_und_aktualisiere(tmp_path, api_antwort(), lade, Befehle(), "py", ausgaben.append) == "aktuell"

    def offline(url, timeout):
        raise OSError("kein Netz")

    assert pruefe_und_aktualisiere(tmp_path, offline, lade, Befehle(), "py", ausgaben.append) == "offline"


def test_laeuft_erkennt_focusguard_prozess():
    assert laeuft(lambda: [("pythonw.exe", r'"C:\x\.venv\Scripts\pythonw.exe" -m focusguard')])
    assert not laeuft(lambda: [("pythonw.exe", r'"C:\x\pythonw.exe" anderes.py'), ("python.exe", "-m focusguard")])
    assert not laeuft(lambda: [])


def test_verknuepfungen_befehl(tmp_path):
    befehl = verknuepfungen_befehl(tmp_path)
    skript = " ".join(befehl)
    assert befehl[0].lower().startswith("powershell")
    for teil in ("FocusGuard.lnk", "FocusGuard aktualisieren.lnk", "--starten", "--aktualisieren",
                 str(tmp_path / "updater.py"), str(venv_python(tmp_path))):
        assert teil in skript


def test_wurzel_aus_app_ordner(tmp_path):
    assert wurzel_aus(tmp_path / "updater.py") == tmp_path
    assert wurzel_aus(tmp_path / "app" / "updater.py") == tmp_path


def test_main_starten_startet_app_auch_offline(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()
    gestartet = []
    monkeypatch.setattr(updater, "hole_json", lambda url, timeout: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(updater, "windows_prozesse", lambda: [])
    monkeypatch.setattr(updater, "starte_app", lambda root: gestartet.append(root))
    monkeypatch.setattr(updater.time, "sleep", lambda s: None)
    assert updater.main(["--starten", "--ziel", str(tmp_path)]) == 0
    assert gestartet == [tmp_path]


def test_main_starten_nicht_doppelt(tmp_path, monkeypatch):
    gestartet = []
    monkeypatch.setattr(updater, "windows_prozesse", lambda: [("pythonw.exe", "pythonw.exe -m focusguard")])
    monkeypatch.setattr(updater, "starte_app", lambda root: gestartet.append(root))
    monkeypatch.setattr(updater.time, "sleep", lambda s: None)
    assert updater.main(["--starten", "--ziel", str(tmp_path)]) == 0
    assert gestartet == []


def test_verknuepfungen_nur_unter_windows(tmp_path, monkeypatch):
    b = Befehle()
    monkeypatch.setattr(updater.sys, "platform", "linux")
    assert updater.erstelle_verknuepfungen(tmp_path, b) is False and b.liste == []
    monkeypatch.setattr(updater.sys, "platform", "win32")
    assert updater.erstelle_verknuepfungen(tmp_path, b) is True and len(b.liste) == 1
