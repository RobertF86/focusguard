"""KI-Qualität prüfen: echte Beispielbilder gegen erwartete Urteile.

Aufruf:  python tools/ki_check.py <ordner>

Der Ordner enthält die Bilder und eine Datei erwartet.toml, zum Beispiel:

    [[fall]]
    datei = "blender_tutorial.jpg"
    art = "seite"              # seite | handy | stichprobe
    aufgabe = "Blender-Grundlagen lernen"
    erwartet = "fokus"         # fokus | abgelenkt
    prozess = "chrome.exe"     # optional, nur für art = "seite"
    titel = "Donut Tutorial - YouTube"
    url = "https://www.youtube.com/watch?v=…"

Das Modell kommt aus der Umgebungsvariable FOCUSGUARD_MODELL (Standard: claude-haiku-5-5).
"""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path

from focusguard.ai.client import Sender, anthropic_sender
from focusguard.ai.prompts import (SYSTEM_URTEIL, URTEIL_SCHEMA, baue_anfrage, handy_inhalt, parse_urteil,
                                   seite_inhalt, stichprobe_inhalt)
from focusguard.sensors.pc import beobachtung_aus


def lade_faelle(pfad: Path) -> list[dict]:
    daten = tomllib.loads((Path(pfad) / "erwartet.toml").read_text(encoding="utf-8"))
    return list(daten.get("fall", []))


def _inhalt(fall: dict, bild: bytes) -> list[dict]:
    if fall["art"] == "seite":
        pc = beobachtung_aus(0.0, 0, fall.get("prozess", "unbekannt.exe"), fall.get("titel", ""), fall.get("url"))
        return seite_inhalt(fall["aufgabe"], pc, bild)
    if fall["art"] == "handy":
        return handy_inhalt(fall["aufgabe"], bild)
    return stichprobe_inhalt(fall["aufgabe"], None, [bild], None)


def pruefe(faelle: list[dict], ordner: Path, sender: Sender, modell: str) -> tuple[int, int]:
    treffer = 0
    for fall in faelle:
        bild = (Path(ordner) / fall["datei"]).read_bytes()
        anfrage = baue_anfrage(modell, SYSTEM_URTEIL, _inhalt(fall, bild), URTEIL_SCHEMA)
        try:
            urteil = parse_urteil(sender(anfrage).text, 0.6)
            ergebnis, begruendung = urteil.status.value, urteil.begruendung
        except Exception as e:
            ergebnis, begruendung = "fehler", str(e)
        richtig = ergebnis == fall["erwartet"]
        treffer += richtig
        print(f"{'OK    ' if richtig else 'FALSCH'} {fall['datei']}: erwartet {fall['erwartet']}, "
              f"KI sagt {ergebnis} – {begruendung}")
    print(f"\n{treffer} von {len(faelle)} richtig")
    return treffer, len(faelle)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__)
        return 2
    ordner = Path(argv[0])
    modell = os.environ.get("FOCUSGUARD_MODELL", "claude-haiku-5-5")
    treffer, gesamt = pruefe(lade_faelle(ordner), ordner, anthropic_sender(), modell)
    return 0 if treffer == gesamt else 1


if __name__ == "__main__":
    sys.exit(main())
