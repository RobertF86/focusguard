"""Einstellungen aus settings.toml und der Datenordner."""

from __future__ import annotations

import os
import re
import sys
import tomllib
from dataclasses import dataclass, fields, replace
from pathlib import Path


@dataclass(frozen=True)
class SensorEinst:
    pc: bool = True
    webcam: bool = True
    smartphone: bool = True


@dataclass(frozen=True)
class KiEinst:
    modell: str = "claude-haiku-5-5"
    max_aufrufe_pro_minute: int = 2
    stichprobe_sekunden: int = 120
    stichprobe_nachpruefung_sekunden: int = 30
    handy_pruefung_sekunden: int = 60
    min_sicherheit: float = 0.6
    bilder_speichern: bool = False


@dataclass(frozen=True)
class ErkennungEinst:
    handy_mindestdauer_sekunden: int = 3
    kopf_gesenkt_grad: float = 20.0
    abwesend_nach_sekunden: int = 15
    begruessung_ab_minuten: int = 5


@dataclass(frozen=True)
class EskalationEinst:
    stufe1_sekunden: int = 10
    stufe2_sekunden: int = 40
    stufe3_sekunden: int = 70
    rueckfall_fenster_minuten: int = 5
    reset_nach_fokus_minuten: int = 5


@dataclass(frozen=True)
class ListenEinst:
    ablenkung_domains: tuple[str, ...] = ("instagram.com", "tiktok.com", "facebook.com", "netflix.com",
                                          "twitch.tv", "9gag.com")
    ablenkung_programme: tuple[str, ...] = ("steam.exe", "epicgameslauncher.exe")
    nie_sperren: tuple[str, ...] = ("explorer.exe", "taskmgr.exe", "python.exe", "pythonw.exe")
    # Kurz eingeblendete System- und Werkzeugfenster: Sie ändern das Urteil nicht und lösen keine KI-Frage aus.
    neutral_programme: tuple[str, ...] = ("searchhost.exe", "searchapp.exe", "startmenuexperiencehost.exe",
                                          "shellexperiencehost.exe", "lockapp.exe", "sharex.exe", "snippingtool.exe",
                                          "screenclippinghost.exe")


@dataclass(frozen=True)
class Einstellungen:
    sensoren: SensorEinst = SensorEinst()
    ki: KiEinst = KiEinst()
    erkennung: ErkennungEinst = ErkennungEinst()
    eskalation: EskalationEinst = EskalationEinst()
    listen: ListenEinst = ListenEinst()


STANDARD_TOML = """\
[sensoren]
pc = true
webcam = true
smartphone = true

[ki]
modell = "claude-haiku-5-5"
max_aufrufe_pro_minute = 2
stichprobe_sekunden = 120
stichprobe_nachpruefung_sekunden = 30
handy_pruefung_sekunden = 60
min_sicherheit = 0.6
bilder_speichern = false

[erkennung]
handy_mindestdauer_sekunden = 3
kopf_gesenkt_grad = 20
abwesend_nach_sekunden = 15
begruessung_ab_minuten = 5

[eskalation]
stufe1_sekunden = 10      # zugleich die Gnadenfrist
stufe2_sekunden = 40
stufe3_sekunden = 70
rueckfall_fenster_minuten = 5
reset_nach_fokus_minuten = 5

[listen]
ablenkung_domains = ["instagram.com", "tiktok.com", "facebook.com", "netflix.com", "twitch.tv", "9gag.com"]
ablenkung_programme = ["steam.exe", "epicgameslauncher.exe"]
nie_sperren = ["explorer.exe", "taskmgr.exe", "python.exe", "pythonw.exe"]
# ändern das Urteil nicht (Desktop, Alt+Tab und Explorer ohne Fenstertitel sind immer neutral)
neutral_programme = ["searchhost.exe", "searchapp.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe",
                     "lockapp.exe", "sharex.exe", "snippingtool.exe", "screenclippinghost.exe"]
"""


class EinstellungsFehler(Exception):
    pass


def _pruefe_wert(abschnitt: str, schluessel: str, wert, standard):
    name = f"{abschnitt}.{schluessel}"
    if isinstance(standard, bool):
        if not isinstance(wert, bool):
            raise EinstellungsFehler(f"{name}: true oder false erwartet")
        return wert
    if isinstance(standard, (int, float)):
        if isinstance(wert, bool) or not isinstance(wert, (int, float)):
            raise EinstellungsFehler(f"{name}: Zahl erwartet")
        if isinstance(standard, int) and not isinstance(standard, bool) and isinstance(wert, float):
            if not wert.is_integer():
                raise EinstellungsFehler(f"{name}: ganze Zahl erwartet")
            return int(wert)
        return wert
    if isinstance(standard, str):
        if not isinstance(wert, str):
            raise EinstellungsFehler(f"{name}: Text erwartet")
        return wert
    if isinstance(standard, tuple):
        if not isinstance(wert, list) or not all(isinstance(x, str) for x in wert):
            raise EinstellungsFehler(f"{name}: Liste von Texten erwartet")
        return tuple(wert)
    raise EinstellungsFehler(f"{name}: unbekannter Typ")


def lade_einstellungen(pfad: Path) -> Einstellungen:
    pfad = Path(pfad)
    if not pfad.exists():
        pfad.parent.mkdir(parents=True, exist_ok=True)
        pfad.write_text(STANDARD_TOML, encoding="utf-8")
    try:
        daten = tomllib.loads(pfad.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise EinstellungsFehler(f"settings.toml ist ungültig: {e}") from e

    ergebnis = Einstellungen()
    for abschnitt_feld in fields(Einstellungen):
        abschnitt = abschnitt_feld.name
        roh = daten.get(abschnitt)
        if roh is None:
            continue
        if not isinstance(roh, dict):
            raise EinstellungsFehler(f"{abschnitt}: Abschnitt erwartet")
        standard_abschnitt = getattr(ergebnis, abschnitt)
        werte = {}
        for f in fields(standard_abschnitt):
            if f.name in roh:
                werte[f.name] = _pruefe_wert(abschnitt, f.name, roh[f.name], getattr(standard_abschnitt, f.name))
        ergebnis = replace(ergebnis, **{abschnitt: replace(standard_abschnitt, **werte)})
    return ergebnis


def setze_sensor(pfad: Path, name: str, wert: bool) -> None:
    pfad = Path(pfad)
    text = pfad.read_text(encoding="utf-8")
    block = re.search(r"^\[sensoren\][^\[]*", text, flags=re.MULTILINE)
    neu_wert = "true" if wert else "false"
    if block is None:
        text = text.rstrip("\n") + f"\n\n[sensoren]\n{name} = {neu_wert}\n"
    else:
        inhalt = block.group(0)
        muster = re.compile(rf"^({re.escape(name)}\s*=\s*)(true|false)", flags=re.MULTILINE)
        if muster.search(inhalt):
            inhalt_neu = muster.sub(rf"\g<1>{neu_wert}", inhalt, count=1)
        else:
            inhalt_neu = inhalt.rstrip("\n") + f"\n{name} = {neu_wert}\n\n"
        text = text[:block.start()] + inhalt_neu + text[block.end():]
    pfad.write_text(text, encoding="utf-8")


def datenordner() -> Path:
    if os.environ.get("FOCUSGUARD_HOME"):
        ordner = Path(os.environ["FOCUSGUARD_HOME"])
    elif sys.platform == "win32" and os.environ.get("APPDATA"):
        ordner = Path(os.environ["APPDATA"]) / "FocusGuard"
    else:
        ordner = Path.home() / ".focusguard"
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner
