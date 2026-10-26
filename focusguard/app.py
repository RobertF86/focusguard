"""App-Start: Verdrahtung aller Bausteine, Selbsttest (--pruefen) und Kamera-Test (--kamera-test)."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

from .config import Einstellungen, EinstellungsFehler, datenordner, lade_einstellungen, setze_sensor
from .models import aufgabe_key

TICK_MS = 250
KI_LEERLAUF_S = 0.5

# Alle Module, die die Tray-App beim Start braucht. Der Updater ruft `--importtest` nach jedem Update auf
# und rollt zurück, wenn hier etwas nicht lädt.
APP_MODULE = ("focusguard.steuerung", "focusguard.storage", "focusguard.ui.tray", "focusguard.ui.start_dialog",
              "focusguard.blocker", "focusguard.capture", "focusguard.sensors.verwaltung", "focusguard.ai.client")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="focusguard", description="FocusGuard – dein Fokus-Wächter")
    parser.add_argument("--pruefen", action="store_true", help="Installation prüfen und Modelle herunterladen")
    parser.add_argument("--kamera-test", action="store_true", help="Gesicht, Kopfneigung und Handy live anzeigen")
    parser.add_argument("--importtest", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    uebernimm_api_schluessel()
    if args.importtest:
        return importtest()
    if args.pruefen:
        return pruefen()
    if args.kamera_test:
        return kamera_test()
    return starte_app()


def _registry_schluessel() -> str | None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as schluessel:
            wert, _ = winreg.QueryValueEx(schluessel, "ANTHROPIC_API_KEY")
    except OSError:
        return None
    return wert if isinstance(wert, str) and wert.strip() else None


def uebernimm_api_schluessel(umgebung=None, plattform: str = sys.platform, lies_registry=_registry_schluessel) -> None:
    """Ein gerade erst gespeicherter Schlüssel fehlt in Prozessen, die vorher gestartet wurden. Unter Windows
    steht er dann schon in der Registry (HKCU\\Environment); von dort übernehmen wir ihn."""
    umgebung = os.environ if umgebung is None else umgebung
    if umgebung.get("ANTHROPIC_API_KEY") or plattform != "win32":
        return
    wert = lies_registry()
    if wert:
        umgebung["ANTHROPIC_API_KEY"] = wert


# --- Selbsttest ------------------------------------------------------------------------------------

def version_text(datei: Path | None = None) -> str:
    """Installierter Stand laut version.json des Updaters (liegt neben dem Ordner app)."""
    datei = datei or Path(__file__).resolve().parents[2] / "version.json"
    try:
        v = json.loads(datei.read_text(encoding="utf-8"))
        text = f"{v['sha'][:7]} – {v.get('nachricht', '')}"
    except (OSError, ValueError, KeyError, TypeError):
        return "Entwicklungsstand"
    return text.rstrip(" –")


def _zeile(ok: bool, name: str, grund: str = "") -> bool:
    print(f"[OK] {name}" if ok else f"[FEHLT] {name}: {grund}", flush=True)
    return ok


def _importiere_app_module() -> None:
    for modul in APP_MODULE:
        importlib.import_module(modul)


def importtest() -> int:
    try:
        _importiere_app_module()
    except Exception:
        import traceback

        traceback.print_exc()
        return 1
    return 0


def pruefen() -> int:
    from .sensors.modelle import GESICHT_MODELL, OBJEKT_MODELL, ModellFehler, stelle_modell_bereit

    print(f"FocusGuard-Version: {version_text()}", flush=True)
    alles_ok = _zeile(sys.version_info >= (3, 12), "Python >= 3.12", f"gefunden: {platform.python_version()}")
    pakete = ["PySide6", "mediapipe", "cv2", "mss", "anthropic"]
    if sys.platform == "win32":
        pakete += ["win32gui", "uiautomation"]
    for paket in pakete:
        try:
            importlib.import_module(paket)
            ok, grund = True, ""
        except Exception as e:
            ok, grund = False, repr(e)
        alles_ok = _zeile(ok, f"Paket {paket}", grund) and alles_ok

    try:
        _importiere_app_module()
        ok, grund = True, ""
    except Exception as e:
        ok, grund = False, repr(e)
    alles_ok = _zeile(ok, "FocusGuard-Module", grund) and alles_ok

    alles_ok = _zeile(bool(os.environ.get("ANTHROPIC_API_KEY")), "ANTHROPIC_API_KEY gesetzt",
                      'Umgebungsvariable fehlt – setx ANTHROPIC_API_KEY "…" und neues Terminal öffnen') and alles_ok

    try:
        ordner = datenordner()
        probe = ordner / ".schreibtest"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        ok, grund = True, ""
    except Exception as e:
        ok, grund = False, repr(e)
    alles_ok = _zeile(ok, "Datenordner beschreibbar", grund) and alles_ok

    try:
        for modell in (GESICHT_MODELL, OBJEKT_MODELL):
            stelle_modell_bereit(*modell, datenordner() / "modelle")
        ok, grund = True, ""
    except (ModellFehler, OSError) as e:
        ok, grund = False, str(e)
    alles_ok = _zeile(ok, "Modelle vorhanden", grund) and alles_ok

    try:
        from .sensors.kamera import Kamera

        kamera = Kamera()
        ok = kamera.oeffne() and kamera.lies() is not None
        kamera.schliesse()
        grund = "keine Kamera gefunden oder sie wird gerade von einem anderen Programm benutzt"
    except Exception as e:
        ok, grund = False, repr(e)
    alles_ok = _zeile(ok, "Kamera erreichbar", grund) and alles_ok

    print("\nAlles bereit." if alles_ok else "\nBitte die mit [FEHLT] markierten Punkte beheben.", flush=True)
    return 0 if alles_ok else 1


# --- Kamera-Test -----------------------------------------------------------------------------------

def kamera_test() -> int:
    from .sensors.gesicht import GesichtsAnalyse
    from .sensors.handy import HandyErkennung
    from .sensors.kamera import Kamera
    from .sensors.modelle import GESICHT_MODELL, OBJEKT_MODELL, stelle_modell_bereit

    modelle = datenordner() / "modelle"
    try:
        gesicht = GesichtsAnalyse(stelle_modell_bereit(*GESICHT_MODELL, modelle))
        handy = HandyErkennung(stelle_modell_bereit(*OBJEKT_MODELL, modelle))
    except Exception as e:
        print(f"Modelle konnten nicht geladen werden: {e}")
        return 1
    kamera = Kamera()
    if not kamera.oeffne():
        print("Kamera nicht verfügbar.")
        return 1
    print("Kamera-Test läuft – beenden mit Strg+C.", flush=True)
    try:
        while True:
            bild = kamera.lies()
            if bild is None:
                print("Kein Bild von der Kamera.", flush=True)
            else:
                gefunden, pitch = gesicht.analysiere(bild)
                score = handy.analysiere(bild)
                pitch_text = f"{pitch:5.1f}°" if pitch is not None else "   – "
                print(f"Gesicht: {'ja  ' if gefunden else 'nein'}  Pitch: {pitch_text}  Handy: {score:.2f}",
                      flush=True)
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        kamera.schliesse()
        gesicht.schliesse()
        handy.schliesse()
    return 0


# --- Tray-App --------------------------------------------------------------------------------------

def oeffne_einstellungen(pfad, plattform: str | None = None, starte=None, oeffne_url=None) -> None:
    """Unter Windows ist .toml meist keinem Programm zugeordnet, daher immer Notepad."""
    plattform = plattform or sys.platform
    if plattform == "win32":
        (starte or subprocess.Popen)(["notepad.exe", str(pfad)])
        return
    if oeffne_url is None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(pfad)))
    else:
        oeffne_url(pfad)


class _KeinBlocker:
    def pruefe(self, b, gesperrt, fokus):
        return None


def starte_app() -> int:
    from PySide6.QtCore import QFileSystemWatcher, QTimer
    from PySide6.QtWidgets import QApplication

    from .ai.client import KiRichter, anthropic_sender
    from .blocker import windows_blocker
    from .capture import Bildschirm
    from .sensors.verwaltung import standard_verwaltung
    from .steuerung import Steuerung
    from .storage import Speicher
    from .ui.start_dialog import StartDialog
    from .ui.tray import Tray

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("FocusGuard")
    app.setQuitOnLastWindowClosed(False)

    ordner = datenordner()
    einst_pfad = ordner / "settings.toml"
    meldungen: list[str] = []
    try:
        einst = lade_einstellungen(einst_pfad)
    except EinstellungsFehler as e:
        einst = Einstellungen()
        meldungen.append(f"settings.toml ist fehlerhaft, Standardwerte sind aktiv: {e}")
    speicher = Speicher(ordner / "focusguard.db")
    ref: dict = {}

    def st() -> Steuerung:
        return ref["steuerung"]

    richter = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        richter = KiRichter(anthropic_sender(), Bildschirm(lambda: st().kamera_jpeg()), einst.ki.modell,
                            einst.ki.min_sicherheit, einst.ki.max_aufrufe_pro_minute, time.time,
                            ablage=ordner / "bilder" if einst.ki.bilder_speichern else None,
                            aktuelle_pc=lambda: st().aktuelle_pc())
    else:
        meldungen.append("ANTHROPIC_API_KEY fehlt – FocusGuard läuft nur mit Regeln.")
    blocker = windows_blocker(einst.listen.nie_sperren, time.time) if sys.platform == "win32" else _KeinBlocker()

    def gespeicherte_listen(aufgabe: str):
        listen = speicher.lade_listen(aufgabe_key(aufgabe))
        return None if listen.ist_leer() else listen

    def bei_start() -> None:
        if st().aktiv:
            return
        dialog = StartDialog(gespeicherte_listen, richter.startlisten if richter else (lambda a: None))
        if dialog.exec() and dialog.ergebnis() is not None:
            aufgabe, dauer, listen = dialog.ergebnis()
            st().starte_session(aufgabe, dauer, listen)
            tray.setze_session_aktiv(st().aktiv)

    def bei_ende() -> None:
        st().beende_session(vorzeitig=True)
        tray.setze_session_aktiv(False)

    def bei_sensor(name: str, wert: bool) -> None:
        zustand = dict(zip(("pc", "webcam", "smartphone"), st().sensoren))
        zustand[name] = wert
        try:
            setze_sensor(einst_pfad, name, wert)
        except OSError:
            pass
        st().setze_sensoren(zustand["pc"], zustand["webcam"], zustand["smartphone"])

    def bei_auswertung() -> None:
        verlauf = st().verlauf_7_tage()
        if not verlauf:
            tray.hinweis("Noch keine Session in den letzten 7 Tagen.")
            return
        tray.zeige_auswertung(verlauf[-1], verlauf)

    def bei_beenden() -> None:
        st().beende_session(vorzeitig=True, zeigen=False)
        app.quit()

    tray = Tray(sensoren=(einst.sensoren.pc, einst.sensoren.webcam, einst.sensoren.smartphone),
                bei_start=bei_start, bei_ende=bei_ende, bei_sensor=bei_sensor,
                bei_aufheben=lambda: st().sperren_aufheben(),
                bei_einstellungen=lambda: oeffne_einstellungen(einst_pfad),
                bei_auswertung=bei_auswertung, bei_beenden=bei_beenden,
                zurueck=lambda: st().zurueck_zur_aufgabe(), gehoert=lambda q: st().gehoert_zur_aufgabe(q))
    steuerung = Steuerung(einst, speicher, tray, lambda aus, feh: standard_verwaltung(aus, feh, ordner), blocker,
                          richter, time.time)
    ref["steuerung"] = steuerung

    stopp = threading.Event()
    if richter is not None:
        def ki_arbeiter() -> None:
            while not stopp.is_set():
                try:
                    ergebnis = richter.verarbeite_naechste()
                except Exception:
                    ergebnis = None
                if ergebnis is None:
                    stopp.wait(KI_LEERLAUF_S)
                else:
                    steuerung.ki_ergebnis(ergebnis)

        threading.Thread(target=ki_arbeiter, name="ki", daemon=True).start()

    war_aktiv = [False]

    def takt() -> None:
        steuerung.tick()
        if steuerung.aktiv != war_aktiv[0]:
            war_aktiv[0] = steuerung.aktiv
            tray.setze_session_aktiv(steuerung.aktiv)

    timer = QTimer()
    timer.timeout.connect(takt)
    timer.start(TICK_MS)

    waechter = QFileSystemWatcher([str(einst_pfad)])

    def einstellungen_neu_laden(_pfad: str = "") -> None:
        if str(einst_pfad) not in waechter.files() and einst_pfad.exists():
            waechter.addPath(str(einst_pfad))   # manche Editoren ersetzen die Datei beim Speichern
        try:
            steuerung.setze_einstellungen(lade_einstellungen(einst_pfad))
        except EinstellungsFehler as e:
            tray.hinweis(f"settings.toml ist fehlerhaft – die alten Einstellungen bleiben aktiv: {e}")

    waechter.fileChanged.connect(einstellungen_neu_laden)

    def aufraeumen() -> None:
        stopp.set()
        timer.stop()
        steuerung.beende_session(vorzeitig=True, zeigen=False)
        speicher.schliesse()

    app.aboutToQuit.connect(aufraeumen)
    tray.show()
    for meldung in meldungen:
        tray.hinweis(meldung)
    return app.exec()
