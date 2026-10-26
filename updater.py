"""FocusGuard – Installer und Updater (nur Python-Standardbibliothek).

Aufrufe:
  python updater.py --installieren [--branch NAME] [--ziel ORDNER]   Erstinstallation (vom Installer-Skript)
  python updater.py --starten                                         Update prüfen, dann FocusGuard starten
  python updater.py --aktualisieren                                   Nur aktualisieren (eigene Verknüpfung)

Aufbau der Installation (Standard: %LOCALAPPDATA%\\Programs\\FocusGuard):
  app\\          der Code aus dem GitHub-Archiv (wird bei jedem Update komplett ersetzt)
  .venv\\        Python-Umgebung mit allen Paketen (bleibt erhalten)
  updater.py    eine Kopie dieses Skripts; die Verknüpfungen rufen sie auf
  update.json   woher Updates kommen (Repo, Branch, Unterordner; leer = ganzes Repo)
  version.json  installierter Stand (Commit, Nachricht, Hash von pyproject.toml)
Einstellungen und Daten liegen getrennt davon in %APPDATA%\\FocusGuard und bleiben bei Updates unberührt.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

REPO = "RobertF86/focusguard"
STANDARD_BRANCH = "main"
UNTERORDNER = ""                  # FocusGuard liegt direkt im Repo; ein Name hier entpackt nur diesen Ordner
PRUEF_TIMEOUT_S = 8
DOWNLOAD_TIMEOUT_S = 60
USER_AGENT = "FocusGuard-Updater"
UMBENENNEN_VERSUCHE = 10          # Virenscanner und Suchindex halten frische Dateien oft kurz fest
UMBENENNEN_PAUSE_S = 0.5
START_PRUEFEN_S = 4               # so lange wird nach dem Start auf einen sofortigen Absturz geachtet


class UpdateFehler(Exception):
    pass


@dataclass(frozen=True)
class Konfig:
    repo: str
    branch: str
    unterordner: str


@dataclass(frozen=True)
class Stand:
    sha: str
    nachricht: str


# --- Pfade und Dateien -----------------------------------------------------------------------------

def standard_wurzel() -> Path:
    basis = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(basis) / "Programs" / "FocusGuard"


def datenordner() -> Path:
    if os.environ.get("FOCUSGUARD_HOME"):
        ordner = Path(os.environ["FOCUSGUARD_HOME"])
    elif sys.platform == "win32" and os.environ.get("APPDATA"):
        ordner = Path(os.environ["APPDATA"]) / "FocusGuard"
    else:
        ordner = Path.home() / ".focusguard"
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner


def wurzel_aus(skript: Path) -> Path:
    ordner = Path(skript).absolute().parent
    return ordner.parent if ordner.name == "app" else ordner


def venv_python(root: Path, fenster: bool = False) -> Path:
    if sys.platform == "win32":
        return root / ".venv" / "Scripts" / ("pythonw.exe" if fenster else "python.exe")
    return root / ".venv" / "bin" / "python"


def _lies_json(datei: Path) -> dict:
    try:
        daten = json.loads(datei.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return daten if isinstance(daten, dict) else {}


def _schreibe_json(datei: Path, daten: dict) -> None:
    datei.parent.mkdir(parents=True, exist_ok=True)
    datei.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")


def lade_konfig(root: Path) -> Konfig:
    daten = _lies_json(root / "update.json")

    def wert(name: str, standard: str) -> str:
        v = daten.get(name)
        return v if isinstance(v, str) and v.strip() else standard

    return Konfig(wert("repo", REPO), wert("branch", STANDARD_BRANCH), wert("unterordner", UNTERORDNER))


def speichere_konfig(root: Path, k: Konfig) -> None:
    _schreibe_json(root / "update.json", {"repo": k.repo, "branch": k.branch, "unterordner": k.unterordner})


def lade_version(root: Path) -> dict:
    return _lies_json(root / "version.json")


def _speichere_version(root: Path, stand: Stand, pyproject_hash: str) -> None:
    _schreibe_json(root / "version.json", {"sha": stand.sha, "nachricht": stand.nachricht,
                                           "pyproject": pyproject_hash,
                                           "installiert": time.strftime("%Y-%m-%d %H:%M:%S")})


def datei_hash(datei: Path) -> str:
    try:
        return hashlib.sha256(datei.read_bytes()).hexdigest()
    except OSError:
        return ""


def _entferne(pfad: Path) -> None:
    if pfad.exists():
        shutil.rmtree(pfad, ignore_errors=True)


# --- GitHub ----------------------------------------------------------------------------------------

def _anfrage(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})


def hole_json(url: str, timeout: float) -> dict:
    with urllib.request.urlopen(_anfrage(url), timeout=timeout) as antwort:
        return json.load(antwort)


def hole_bytes(url: str, timeout: float) -> bytes:
    with urllib.request.urlopen(_anfrage(url), timeout=timeout) as antwort:
        return antwort.read()


def neuester_stand(k: Konfig, holen=None, timeout: float = PRUEF_TIMEOUT_S) -> Stand:
    holen = holen or hole_json
    url = f"https://api.github.com/repos/{k.repo}/commits/{urllib.parse.quote(k.branch, safe='')}"
    try:
        daten = holen(url, timeout)
    except urllib.error.HTTPError as e:
        if e.code in (404, 422):
            raise UpdateFehler(f"Auf GitHub gibt es das Repo „{k.repo}“ oder darin den Branch „{k.branch}“ nicht "
                               f"(mehr). Bitte update.json prüfen, normal ist \"repo\": \"{REPO}\" und "
                               f"\"branch\": \"{STANDARD_BRANCH}\".") from e
        raise
    sha = daten.get("sha") if isinstance(daten, dict) else None
    if not isinstance(sha, str) or len(sha) != 40:
        raise UpdateFehler("GitHub hat keinen gültigen Stand geliefert")
    nachricht = ((daten.get("commit") or {}).get("message") or "").strip()
    return Stand(sha, nachricht.splitlines()[0] if nachricht else "")


def zip_url(k: Konfig, sha: str) -> str:
    return f"https://github.com/{k.repo}/archive/{sha}.zip"


# --- Entpacken und Einspielen ----------------------------------------------------------------------

def entpacke_unterordner(daten: bytes, unterordner: str, ziel: Path) -> None:
    """Entpackt <oberster Ordner>/<unterordner>/… aus dem GitHub-Archiv nach ziel/…; ohne Unterordner alles."""
    _entferne(ziel)
    ziel.mkdir(parents=True)
    basis = ziel.resolve()
    vorne = 2 if unterordner else 1
    with zipfile.ZipFile(io.BytesIO(daten)) as archiv:
        for eintrag in archiv.infolist():
            teile = PurePosixPath(eintrag.filename).parts
            if len(teile) <= vorne or (unterordner and teile[1] != unterordner) or eintrag.is_dir():
                continue
            relativ = teile[vorne:]
            pfad = ziel.joinpath(*relativ).resolve()
            if ".." in relativ or basis not in pfad.parents:
                raise UpdateFehler(f"Ungültiger Pfad im Archiv: {eintrag.filename}")
            pfad.parent.mkdir(parents=True, exist_ok=True)
            pfad.write_bytes(archiv.read(eintrag))
    if not (ziel / "pyproject.toml").exists():
        wo = f"der Ordner {unterordner} mit " if unterordner else ""
        raise UpdateFehler(f"Im Archiv fehlt {wo}pyproject.toml")


def _umbenennen(von: Path, nach: Path) -> None:
    for versuch in range(UMBENENNEN_VERSUCHE):
        try:
            von.rename(nach)
            return
        except OSError:
            if versuch == UMBENENNEN_VERSUCHE - 1:
                raise
            time.sleep(UMBENENNEN_PAUSE_S)


def tausche_ein(root: Path) -> None:
    """Ersetzt app\\ durch app.neu\\; die alte Version bleibt als app.alt\\ liegen, bis das Update geklappt hat."""
    neu, app, alt = root / "app.neu", root / "app", root / "app.alt"
    for rest in root.glob("app.alt*"):
        _entferne(rest)
    if alt.exists():
        _umbenennen(alt, root / f"app.alt-{int(time.time())}")
    if app.exists():
        try:
            _umbenennen(app, alt)
        except OSError as e:
            raise UpdateFehler("Die FocusGuard-Dateien sind noch in Benutzung. Bitte FocusGuard beenden "
                               "und das Update erneut starten.") from e
    try:
        _umbenennen(neu, app)
    except OSError as e:
        if alt.exists() and not app.exists():
            _umbenennen(alt, app)
        raise UpdateFehler(f"Die neue Version konnte nicht eingespielt werden: {e}") from e


def _zurueckrollen(root: Path) -> None:
    app, alt = root / "app", root / "app.alt"
    if app.exists():
        shutil.rmtree(app, ignore_errors=True)
        if app.exists():
            _umbenennen(app, root / f"app.kaputt-{int(time.time())}")
    _umbenennen(alt, app)


def fuehre_aus(befehl: list, cwd: Path | None = None) -> None:
    befehl = [str(t) for t in befehl]
    try:
        subprocess.run(befehl, check=True, cwd=str(cwd) if cwd else None)
    except FileNotFoundError as e:
        raise UpdateFehler(f"{Path(befehl[0]).name} wurde nicht gefunden") from e
    except subprocess.CalledProcessError as e:
        raise UpdateFehler(f"{Path(befehl[0]).name} {befehl[1] if len(befehl) > 1 else ''} ist fehlgeschlagen "
                           f"(Code {e.returncode})") from e


def _kopiere_updater(root: Path) -> None:
    quelle = root / "app" / "updater.py"
    if not quelle.exists():
        return
    zwischen = root / "updater.py.neu"
    try:
        shutil.copyfile(quelle, zwischen)
        os.replace(zwischen, root / "updater.py")
    except OSError:
        pass   # die alte Kopie funktioniert weiter; beim nächsten Update erneut versuchen


def wende_an(root: Path, k: Konfig, stand: Stand, holen_bytes, ausfuehren, python_fuer_venv: str,
             pip_erzwingen: bool = False) -> bool:
    """Lädt den Stand herunter und spielt ihn ein. Gibt zurück, ob pip laufen musste.

    Scheitern pip oder der Importtest, kommt die bisherige Version zurück (sofern es eine gab)."""
    root.mkdir(parents=True, exist_ok=True)
    neu = root / "app.neu"
    try:
        entpacke_unterordner(holen_bytes(zip_url(k, stand.sha), DOWNLOAD_TIMEOUT_S), k.unterordner, neu)
    except UpdateFehler:
        _entferne(neu)
        raise
    except Exception as e:
        _entferne(neu)
        raise UpdateFehler(f"Download fehlgeschlagen: {e}") from e

    neuer_hash = datei_hash(neu / "pyproject.toml")
    alter_hash = lade_version(root).get("pyproject")
    tausche_ein(root)

    try:
        venv_fehlt = not venv_python(root).exists()
        if venv_fehlt:
            ausfuehren([python_fuer_venv, "-m", "venv", str(root / ".venv")])
        pip_noetig = pip_erzwingen or venv_fehlt or neuer_hash != alter_hash
        if pip_noetig:
            ausfuehren([str(venv_python(root)), "-m", "pip", "install", "-e", str(root / "app")])
        ausfuehren([str(venv_python(root)), "-m", "focusguard", "--importtest"])
    except Exception as e:
        if not (root / "app.alt").exists():
            raise e if isinstance(e, UpdateFehler) else UpdateFehler(str(e))
        try:
            _zurueckrollen(root)
        except OSError as rollback_fehler:
            raise UpdateFehler(f"{e} – und die bisherige Version ließ sich nicht wiederherstellen "
                               f"({rollback_fehler}). Bitte den Installer erneut ausführen.") from e
        raise UpdateFehler(f"{e} – FocusGuard bleibt auf der bisherigen Version.") from e
    _entferne(root / "app.alt")
    _kopiere_updater(root)
    _speichere_version(root, stand, neuer_hash)   # erst ganz am Ende: ein Fehler davor wird beim nächsten Mal wiederholt
    return pip_noetig


def pruefe_und_aktualisiere(root: Path, holen_json, holen_bytes, ausfuehren, python_fuer_venv: str,
                            ausgabe=print) -> str:
    """Ergebnis: "aktuell", "aktualisiert" oder "offline"."""
    k = lade_konfig(root)
    try:
        stand = neuester_stand(k, holen_json)
    except Exception as e:
        ausgabe(f"Update-Prüfung nicht möglich ({e}).")
        return "offline"
    if lade_version(root).get("sha") == stand.sha and (root / "app").exists():
        return "aktuell"
    ausgabe(f"Neue Version {stand.sha[:7]}: {stand.nachricht}")
    if wende_an(root, k, stand, holen_bytes, ausfuehren, python_fuer_venv):
        ausgabe("Pakete wurden installiert.")
    ausgabe("Update installiert.")
    return "aktualisiert"


# --- Windows: Prozesse, Verknüpfungen, API-Schlüssel, Start -----------------------------------------

def windows_prozesse() -> list[tuple[str, str]]:
    if sys.platform != "win32":
        return []
    skript = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
              "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | "
              "ForEach-Object { $_.Name + '|' + $_.CommandLine }")
    try:
        ausgabe = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", skript],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return []
    return [tuple(zeile.split("|", 1)) for zeile in ausgabe.splitlines() if "|" in zeile]


def laeuft(prozesse=None) -> bool:
    prozesse = prozesse or windows_prozesse
    return any(name.lower() == "pythonw.exe" and "-m focusguard" in (befehl or "").lower()
               for name, befehl in prozesse())


def _ps_text(wert) -> str:
    return "'" + str(wert).replace("'", "''") + "'"


def verknuepfungen_befehl(root: Path) -> list[str]:
    python, updater = venv_python(root), root / "updater.py"
    skript = "\n".join([
        "$ws = New-Object -ComObject WScript.Shell",
        "$ordner = @([Environment]::GetFolderPath('Desktop'), "
        "(Join-Path ([Environment]::GetFolderPath('Programs')) 'FocusGuard'))",
        "foreach ($o in $ordner) {",
        "  New-Item -ItemType Directory -Force -Path $o | Out-Null",
        "  foreach ($e in @(@('FocusGuard.lnk', '--starten'), @('FocusGuard aktualisieren.lnk', '--aktualisieren'))) {",
        "    $s = $ws.CreateShortcut((Join-Path $o $e[0]))",
        f"    $s.TargetPath = {_ps_text(python)}",
        f"    $s.Arguments = {_ps_text(chr(34) + str(updater) + chr(34) + ' ')} + $e[1]",
        f"    $s.WorkingDirectory = {_ps_text(root)}",
        "    $s.Save()",
        "  }",
        "}",
    ])
    return ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", skript]


def erstelle_verknuepfungen(root: Path, ausfuehren=fuehre_aus) -> bool:
    if sys.platform != "win32":
        return False
    ausfuehren(verknuepfungen_befehl(root))
    return True


def lies_api_schluessel() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as schluessel:
                wert, _ = winreg.QueryValueEx(schluessel, "ANTHROPIC_API_KEY")
                return wert or None
        except OSError:
            return None
    return None


def setze_api_schluessel(wert: str) -> None:
    os.environ["ANTHROPIC_API_KEY"] = wert
    if sys.platform == "win32":
        try:
            subprocess.run(["setx", "ANTHROPIC_API_KEY", wert], check=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError) as e:
            raise UpdateFehler("Der API-Schlüssel konnte nicht gespeichert werden") from e


def starte_app(root: Path) -> subprocess.Popen:
    """Startet FocusGuard ohne Konsole; Ausgaben und Fehler landen in %APPDATA%\\FocusGuard\\start.log."""
    pythonw = venv_python(root, fenster=True)
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    with open(datenordner() / "start.log", "w", encoding="utf-8") as log:
        return subprocess.Popen([str(pythonw), "-m", "focusguard"], cwd=str(root), creationflags=flags,
                                close_fds=True, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)


def warte_auf_start(proz, root: Path, sekunden: float = START_PRUEFEN_S) -> bool:
    """False, wenn FocusGuard sofort wieder beendet wurde; dann wird der Grund aus start.log gezeigt."""
    if proz is None:
        return True
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        if proz.poll() is not None:
            break
        time.sleep(0.25)
    code = proz.poll()
    if code is None or code == 0:
        return True
    log = datenordner() / "start.log"
    try:
        zeilen = log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
    except OSError:
        zeilen = []
    print(f"\nFocusGuard wurde beim Start sofort wieder beendet (Code {code}). Letzte Zeilen aus start.log:\n")
    print("\n".join(zeilen) or "(leer)")
    print(f"\nDie ganze Datei liegt hier: {log}\nBitte schick mir diese Zeilen als Feedback.")
    input("\nEnter zum Schließen …")
    return False


# --- Abläufe ---------------------------------------------------------------------------------------

def installieren(root: Path, branch: str | None) -> int:
    if "windowsapps" in sys.executable.lower():
        print("Dieses Python stammt aus dem Microsoft Store. Damit funktionieren die Verknüpfungen nicht zuverlässig.\n"
              "Bitte Python von https://www.python.org/downloads/ installieren und den Installer erneut starten.")
        return 1
    print(f"FocusGuard wird installiert nach: {root}\n")
    if laeuft():
        print("FocusGuard läuft gerade. Bitte über das Tray-Symbol → „Beenden“ schließen und den Installer erneut "
              "starten.")
        return 1
    k = Konfig(REPO, branch or STANDARD_BRANCH, UNTERORDNER)
    speichere_konfig(root, k)
    try:
        stand = neuester_stand(k)
        print(f"Lade Version {stand.sha[:7]}: {stand.nachricht}")
        print("Beim ersten Mal werden alle Pakete installiert, das dauert einige Minuten …\n")
        wende_an(root, k, stand, hole_bytes, lambda b: fuehre_aus(b, cwd=root), sys.executable, pip_erzwingen=True)
    except Exception as e:
        print(f"\nInstallation fehlgeschlagen: {e}")
        return 1

    if not lies_api_schluessel():
        print("\nFür die KI-Beurteilung braucht FocusGuard deinen Anthropic-API-Schlüssel "
              "(https://console.anthropic.com/).")
        wert = getpass.getpass("Schlüssel einfügen und Enter drücken (die Eingabe bleibt unsichtbar; "
                               "nur Enter = später): ").strip()
        if wert:
            try:
                setze_api_schluessel(wert)
                print("API-Schlüssel gespeichert.")
            except UpdateFehler as e:
                print(e)

    print("\nPrüfe die Installation und lade die Bild-Modelle …\n")
    try:
        fuehre_aus([venv_python(root), "-m", "focusguard", "--pruefen"], cwd=root)
    except UpdateFehler:
        print("(Die mit [FEHLT] markierten Punkte kannst du später beheben.)")
    try:
        verknuepft = erstelle_verknuepfungen(root)
    except UpdateFehler as e:
        print(f"\nVerknüpfungen konnten nicht angelegt werden: {e}")
        verknuepft = False
    if verknuepft:
        print("\nVerknüpfungen „FocusGuard“ und „FocusGuard aktualisieren“ liegen auf dem Desktop und im Startmenü.")
        print("\nFertig! Starte FocusGuard über die Verknüpfung „FocusGuard“ auf dem Desktop.")
    else:
        print(f"\nFertig! Starten mit:\n  \"{venv_python(root)}\" \"{root / 'updater.py'}\" --starten")
    return 0


def starten(root: Path) -> int:
    if laeuft():
        print("FocusGuard läuft bereits – das Symbol findest du rechts unten in der Taskleiste.")
        time.sleep(4)
        return 0
    print("Suche nach Updates …")
    try:
        if pruefe_und_aktualisiere(root, hole_json, hole_bytes, lambda b: fuehre_aus(b, cwd=root),
                                   sys.executable) == "aktuell":
            print("FocusGuard ist aktuell.")
    except Exception as e:
        print(f"Update fehlgeschlagen: {e}\nFocusGuard startet mit der bisherigen Version.")
        time.sleep(8)
    if not (root / "app").exists():
        print("FocusGuard ist nicht installiert. Bitte den Installer erneut ausführen.")
        time.sleep(8)
        return 1
    print("Starte FocusGuard …")
    return 0 if warte_auf_start(starte_app(root), root) else 1


def aktualisieren(root: Path) -> int:
    if laeuft():
        print("FocusGuard läuft gerade. Bitte über das Tray-Symbol (rechts unten) → „Beenden“ schließen.")
        print("Ich warte … (Abbrechen mit Strg+C)")
        while laeuft():
            time.sleep(2)
    try:
        ergebnis = pruefe_und_aktualisiere(root, hole_json, hole_bytes, lambda b: fuehre_aus(b, cwd=root),
                                           sys.executable)
    except Exception as e:
        print(f"Update fehlgeschlagen: {e}")
        input("\nEnter zum Schließen …")
        return 1
    if ergebnis == "aktuell":
        print(f"Du hast bereits die neueste Version ({lade_version(root).get('sha', '')[:7]}).")
    elif ergebnis == "offline":
        print("Keine Verbindung zu GitHub – bitte später erneut versuchen.")
    if input("\nFocusGuard jetzt starten? [J/n] ").strip().lower() not in ("n", "nein"):
        return 0 if warte_auf_start(starte_app(root), root) else 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="updater.py", description="FocusGuard installieren und aktualisieren")
    modus = parser.add_mutually_exclusive_group(required=True)
    modus.add_argument("--installieren", action="store_true", help="Erstinstallation")
    modus.add_argument("--starten", action="store_true", help="Update prüfen und FocusGuard starten")
    modus.add_argument("--aktualisieren", action="store_true", help="Nur aktualisieren")
    parser.add_argument("--branch", help="GitHub-Branch, von dem Updates kommen")
    parser.add_argument("--ziel", type=Path, help="Installationsordner (Standard: %%LOCALAPPDATA%%\\Programs\\FocusGuard)")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)   # Meldungen erscheinen in der richtigen Reihenfolge mit pip
    except (AttributeError, ValueError):
        pass
    try:
        if args.installieren:
            return installieren(args.ziel or standard_wurzel(), args.branch)
        root = args.ziel or wurzel_aus(Path(__file__))
        if args.branch:
            speichere_konfig(root, replace(lade_konfig(root), branch=args.branch))
        return starten(root) if args.starten else aktualisieren(root)
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
        return 1
    except Exception:
        print("\nUnerwarteter Fehler:\n")
        traceback.print_exc(file=sys.stdout)
        print("\nBitte schick mir diese Meldung als Feedback.")
        try:
            input("\nEnter zum Schließen …")
        except EOFError:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
