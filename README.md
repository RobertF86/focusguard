# FocusGuard

Ein persönlicher Fokus-Wächter für Windows, Prototyp Version 1.

Du startest eine Session für eine Aufgabe, etwa „Blender-Grundlagen lernen“. Während der Session beobachtet FocusGuard,
was du am PC machst, ob du am Platz bist und ob du zum Handy greifst. Lenkst du dich ab, reagiert die App in Stufen:

1. **nach 10 Sekunden** ein Hinweis mit Ton,
2. **nach 40 Sekunden** ein Vollbild-Overlay auf allen Monitoren,
3. **nach 70 Sekunden** wird die ablenkende Seite oder App für den Rest der Session gesperrt.

Eindeutige Fälle (Instagram, Blender …) entscheidet die App selbst. Unklare Fälle („Ist dieses YouTube-Video ein
Tutorial?“) beurteilt Claude Haiku 5.5. Alles ist freiwillig: Du kannst jede Sperre aufheben und die App jederzeit
beenden.

Die Hintergründe stehen in der Spec (`../docs/superpowers/specs/2026-10-21-focusguard-design.md`).

## Voraussetzungen

- Windows 10 oder 11
- eine Webcam (optional, nur für Abwesenheit und Handy-Erkennung)
- ein Anthropic-API-Schlüssel (<https://console.anthropic.com/>). Ohne Schlüssel läuft FocusGuard nur mit den festen Listen.

Python musst du nicht selbst installieren, das erledigt der Installer.

## Installation

1. Die Datei **`FocusGuard-installieren.bat`** herunterladen:
   <https://raw.githubusercontent.com/RobertF86/ScriptCollection/refs/heads/claude/serene-hamilton-sjzb16/FocusGuard/FocusGuard-installieren.bat>
   (im Browser Rechtsklick → „Speichern unter …“, oder Strg+S).
2. Doppelklick auf die Datei. Zeigt Windows „Der Computer wurde durch Windows geschützt“, auf
   „Weitere Informationen“ → „Trotzdem ausführen“ klicken.
3. Der Installer erledigt dann alles:
   - installiert Python 3.12, falls es fehlt (über `winget`, ohne Admin-Rechte),
   - installiert FocusGuard nach `%LOCALAPPDATA%\Programs\FocusGuard`,
   - installiert alle Pakete (beim ersten Mal einige Minuten),
   - fragt nach deinem API-Schlüssel und speichert ihn,
   - prüft die Installation und lädt die Bild-Modelle (`--pruefen`),
   - legt die Verknüpfungen **„FocusGuard“** und **„FocusGuard aktualisieren“** auf dem Desktop und im Startmenü an.

Den Installer kannst du jederzeit erneut ausführen, zum Beispiel um eine kaputte Installation zu reparieren.

## Updates

- **Automatisch:** Die Verknüpfung „FocusGuard“ prüft bei jedem Start, ob es eine neue Version gibt, spielt sie ein
  und startet dann. Ohne Internet startet einfach die vorhandene Version.
- **Von Hand:** „FocusGuard aktualisieren“. Läuft FocusGuard gerade, wartet das Fenster, bis du es über das
  Tray-Symbol beendest.
- **Welche Version läuft?** Steht in der ersten Zeile von `--pruefen` (siehe unten) und in
  `%LOCALAPPDATA%\Programs\FocusGuard\version.json`. Beim Feedback bitte die sieben Zeichen mit angeben.
- **Woher kommen Updates?** Aus dem Branch, der in `%LOCALAPPDATA%\Programs\FocusGuard\update.json` steht
  (gerade `claude/serene-hamilton-sjzb16`). Nach dem Merge dort `"branch": "master"` eintragen.

Deine Einstellungen und Daten liegen getrennt in `%APPDATA%\FocusGuard\` und bleiben bei Updates erhalten.

## Prüfen und Kamera-Test

In einer Eingabeaufforderung:

```bat
"%LOCALAPPDATA%\Programs\FocusGuard\.venv\Scripts\python.exe" -m focusguard --pruefen
```

Das zeigt die Version und prüft Python, Pakete, API-Schlüssel, Datenordner und Kamera. Jede Zeile sollte mit `[OK]`
beginnen.

Die Kamera-Erkennung live ansehen:

```bat
"%LOCALAPPDATA%\Programs\FocusGuard\.venv\Scripts\python.exe" -m focusguard --kamera-test
```

Du siehst zweimal pro Sekunde `Gesicht: ja/nein  Pitch: …°  Handy: …`. Senkst du den Kopf, sollte der Pitch-Wert
deutlich **steigen**. Hältst du dein Handy in die Kamera, sollte der Handy-Wert über 0.50 gehen. Beenden mit Strg+C.

## Deinstallieren

Den Ordner `%LOCALAPPDATA%\Programs\FocusGuard` und die beiden Verknüpfungen löschen. Deine Daten liegen in
`%APPDATA%\FocusGuard`; lösch den Ordner, wenn du sie nicht mehr brauchst.

## Starten

Doppelklick auf die Verknüpfung **„FocusGuard“**. Rechts unten in der Taskleiste erscheint ein grauer Punkt. Rechtsklick darauf
öffnet das Menü:

| Eintrag | Wirkung |
|---|---|
| Session starten … | Aufgabe und Dauer eingeben, dann die vorgeschlagenen Listen prüfen |
| Session beenden | beendet sofort (wird als „vorzeitig beendet“ vermerkt) |
| PC / Webcam / Smartphone | welche Überwachung läuft; wirkt sofort und wird gespeichert |
| Sperren aufheben | hebt alle Sperren der laufenden Session auf |
| Einstellungen … | öffnet `settings.toml` in Notepad; Änderungen gelten ab der nächsten Session (Modell, KI-Limits, `bilder_speichern` und `nie_sperren` erst nach einem Neustart von FocusGuard) |
| Auswertung … | letzte Session und die letzten 7 Tage |
| Beenden | schließt FocusGuard sofort |

Die Farbe des Icons: grau = keine Session, grün = alles gut, gelb = Hinweis, rot = Overlay oder Sperre,
blau = du bist nicht am Platz.

## Wo die Daten liegen

Alles liegt lokal in `%APPDATA%\FocusGuard\`:

- `settings.toml`: alle Einstellungen (Zeitstufen, Modell, Listen …)
- `focusguard.db`: Sessions, Ereignisse, KI-Urteile, Listen pro Aufgabe
- `modelle\`: die beiden MediaPipe-Modelle
- `bilder\`: nur wenn `bilder_speichern = true`; dort landen die an die KI geschickten Bilder samt Urteil

Screenshots und Webcam-Bilder werden an die Claude-API geschickt. Für diesen Prototyp ist das bewusst so.

## KI-Qualität prüfen

Lege einen Ordner mit Beispielbildern (Screenshots, Webcam-Fotos) und einer `erwartet.toml` an. Das Format steht oben
in `tools/ki_check.py`. Dann:

```bat
python tools\ki_check.py C:\Pfad\zu\beispielen
```

Das Skript zeigt pro Bild, ob Haiku richtig geurteilt hat.

## Test-Checkliste für Windows

Die Logik ist automatisch getestet (`python -m pytest`). Alles, was Windows, Webcam und Bildschirm betrifft, musst du
selbst ausprobieren:

1. Der Installer läuft durch, und `--pruefen` (siehe oben) zeigt nur `[OK]`.
2. `--kamera-test` (siehe oben): „Gesicht“ wechselt auf „nein“, wenn du weggehst; der Pitch steigt deutlich,
   wenn du den Kopf senkst; der Handy-Wert liegt über 0.50, wenn du das Handy hältst.
3. Das Tray-Icon erscheint grau, das Menü zeigt alle Einträge, die Checkboxen bleiben nach einem Neustart erhalten.
4. Session „Blender lernen“ mit 25 Minuten starten: Die Listen-Seite zeigt KI-Vorschläge.
5. Blender im Vordergrund → Icon bleibt grün. Chrome mit docs.blender.org → grün.
6. instagram.com in Chrome und Edge → nach ca. 10 s Hinweis, nach ca. 40 s Overlay auf allen Monitoren,
   nach ca. 70 s wird der Tab geschlossen. In Firefox kann FocusGuard die Adresse nicht auslesen; dort entscheidet die
   KI anhand von Fenstertitel und Screenshot, deshalb kommt der erste Hinweis einige Sekunden später.
7. „Gehört zur Aufgabe“ im Overlay → die Seite bleibt für diese Aufgabe erlaubt.
8. YouTube-Tutorial zu Blender und ein beliebiges anderes Video → unterschiedliche Urteile (siehe Auswertung).
9. Handy in die Hand nehmen und nach unten schauen → nach ca. 3 s gilt das als Ablenkung, nach weiteren 10 s kommt
   der Hinweis (also nach ca. 13 s). Weitermachen → Overlay, nach ca. 73 s das Overlay „Leg das Handy weg“, das etwa
   8 s nach dem Weglegen verschwindet.
10. 6 Minuten weggehen → Icon blau, beim Zurückkommen eine Begrüßung.
11. Video auf dem zweiten Monitor, Blender im Vordergrund → wird innerhalb von ca. 2,5 Minuten erkannt.
12. Kamera durch ein anderes Programm belegen (z. B. Teams-Anruf) → Tooltip zeigt „Kamera nicht verfügbar“, keine
    Abwesenheit.
13. „Sperren aufheben“ und „Beenden“ wirken jederzeit sofort; nach einer Session öffnet sich die Auswertung.
14. `settings.toml` mit einem Tippfehler speichern → Hinweis, die App läuft weiter.

## Entwicklung

Ohne Installer, direkt aus einem Checkout im Ordner `FocusGuard`:

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python -m pytest
start_focusguard.bat
```

