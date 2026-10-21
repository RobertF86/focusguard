# FocusGuard – Design-Spec

Stand: 2026-10-21 · Status: zur Durchsicht

## 1. Ziel

FocusGuard ist ein persönlicher Prototyp gegen Prokrastination am Windows-PC. Die
Person startet freiwillig eine Fokus-Session für eine Aufgabe (z. B. „Blender-Grundlagen
lernen“). Während der Session beobachtet die App PC, Webcam und Smartphone-Nutzung,
erkennt Ablenkung und reagiert in Stufen – vom Hinweis bis zur Sperre der ablenkenden
Seite oder App.

**Erfolg heißt:** mehr konzentrierte Zeit pro Session, sichtbar in der Auswertung, und
spürbarer Fortschritt bei der Aufgabe.

**Grundsätze**

- Freiwillig: Die App lässt sich jederzeit sofort beenden, jede Sperre jederzeit aufheben.
  Vorzeitiges Beenden und Aufheben werden nur protokolliert.
- Fehlalarme sind teurer als verpasste Ablenkungen: Im Zweifel entscheidet die App
  zugunsten der Person.
- Datenschutz ist für den Prototyp bewusst kein Thema (Bilder gehen an die Cloud-KI).

## 2. Umfang

**Version 1 enthält**

- Tray-App für Windows mit drei unabhängig schaltbaren Sensoren: PC, Webcam, Smartphone
  (Smartphone = Erkennung per Webcam).
- Hybride Erkennung: lokale Regeln und Modelle für eindeutige Fälle, Claude Haiku 5.5
  für unklare Fälle und Stichproben.
- Eskalation in drei Stufen mit Sperre ohne Admin-Rechte.
- Lokales Protokoll (SQLite) und Auswertung pro Session.

**Nicht in Version 1**

- Handy-App (Android) – eigenes Folgeprojekt.
- Sperren mit Admin-Rechten (hosts-Datei, Firewall).
- Lokale Bild-KI.
- Installer, Mehrplattform, Datenschutzkonzept, Mitarbeiterüberwachung.
- Einstellungsdialog mit Formularfeldern (v1 öffnet `settings.toml` im Editor, siehe 9.).

## 3. Architektur

Ein Python-Prozess. Qt (PySide6) stellt Event-Loop, Tray und Fenster. Sensoren laufen in
eigenen Threads und liefern Beobachtungen über eine Queue an den Entscheider. Entscheider
und Eskalation sind reine Logik ohne Seiteneffekte: Sie bekommen Beobachtungen und die
aktuelle Zeit und geben Urteile bzw. Aktionen zurück. Seiteneffekte (Fenster, Sperren,
Töne) passieren nur in UI und Blocker.

```
  Sensoren (je per Checkbox)            Logik (rein, testbar)                 Wirkung
  ┌───────────────┐
  │ PC-Sensor     │──┐
  └───────────────┘  │   Beobachtungen  ┌─────────────┐  Urteil  ┌────────────┐  Aktionen  ┌──────────────┐
  ┌───────────────┐  ├─────────────────▶│ Entscheider │─────────▶│ Eskalation │───────────▶│ UI / Blocker │
  │ Webcam-Sensor │──┤                  └──────┬──────┘          └────────────┘            └──────────────┘
  └───────────────┘  │                         │ unklar / Stichprobe
  ┌───────────────┐  │                  ┌──────▼──────┐
  │ Smartphone-   │──┘                  │ KI-Richter  │──▶ Claude Haiku 5.5
  │ Sensor        │                     └─────────────┘
  └───────────────┘
           alle Bausteine ──▶ Protokoll (SQLite) ──▶ Auswertung
```

### 3.1 Projektstruktur

```
FocusGuard/
  pyproject.toml
  README.md                 Start, API-Schlüssel, Test-Checkliste für Windows
  start_focusguard.bat
  focusguard/
    __main__.py
    app.py                  Verdrahtung aller Bausteine, Qt-Event-Loop
    models.py               Status, Beobachtungen, Urteil, Aktionen, Session
    config.py               settings.toml laden, Standardwerte, Neuladen
    clock.py                Uhr-Abstraktion (echte Uhr / Test-Uhr)
    storage.py              SQLite: Sessions, Ereignisse, Gedächtnis, Listen
    sensors/
      base.py               Sensor-Schnittstelle, Thread, Neustart bei Absturz
      pc.py                 Vordergrundfenster, Prozess, URL       (Windows)
      camera.py             gemeinsame Kameraquelle für beide Kamera-Sensoren
      webcam.py             Gesicht vorhanden, Kopfneigung         (MediaPipe)
      phone.py              Handy im Bild                          (YOLO)
    decision/
      rules.py              Fokus-/Ablenkungs-Listen, Abgleich
      memory.py             Gedächtnis der KI-Urteile
      judge.py              Entscheider: kombiniert alles zu einem Urteil
    ai/
      client.py             Claude-Aufrufe, Ratenbegrenzung, Fehlerbehandlung
      prompts.py            Prompts und JSON-Schemas
    escalation.py           Stufenlogik
    blocker.py              Minimieren, Tab schließen               (Windows)
    capture.py              Screenshots                             (mss)
    ui/
      tray.py
      start_dialog.py
      overlay.py
      report.py
  tests/
```

Windows-spezifischer Code steckt nur in `sensors/pc.py`, `blocker.py` und den UI-Modulen.
Alles andere läuft und testet auch unter Linux.

### 3.2 Kernmodelle (`models.py`)

```python
class Status(Enum):
    FOKUS, UNKLAR, ABGELENKT, ABWESEND

@dataclass(frozen=True)
class PcBeobachtung:        # jede Sekunde
    zeit: float
    prozess: str            # z. B. "chrome.exe"
    fenstertitel: str
    url: str | None         # nur wenn auslesbar
    domain: str | None      # aus url abgeleitet, ohne "www."

@dataclass(frozen=True)
class WebcamBeobachtung:    # ca. 2× pro Sekunde
    zeit: float
    gesicht: bool
    kopf_pitch_grad: float | None   # positiv = nach unten geneigt

@dataclass(frozen=True)
class HandyBeobachtung:     # ca. 2× pro Sekunde
    zeit: float
    handy_erkannt: bool
    sicherheit: float

@dataclass(frozen=True)
class Urteil:
    status: Status
    quelle: str             # "domain:instagram.com", "prozess:steam.exe",
                            # "seite:youtube.com|<titel>", "handy", "stichprobe"
    begruendung: str
    herkunft: str           # "regel", "gedaechtnis", "ki", "lokal"
```

Aktionen der Eskalation an UI/Blocker: `Hinweis(text)`, `OverlayZeigen(text, quelle)`,
`OverlaySchliessen()`, `Sperren(quelle)`, `HandyOverlay()`, `Begruessung(minuten_weg)`,
`IconStatus(farbe)`.

## 4. Sensoren

| Sensor | Takt | Liefert | Technik |
|---|---|---|---|
| PC | 1 s | Prozess, Fenstertitel, URL/Domain des Vordergrundfensters | `pywin32`, `psutil`; URL über UI Automation (`uiautomation`) für Chrome, Edge, Brave; bei anderen Browsern (z. B. Firefox) nur Fenstertitel |
| Webcam | ~2/s | Gesicht ja/nein, Kopfneigung | OpenCV-Kamera, MediaPipe Face Landmarker |
| Smartphone | ~2/s | Handy im Bild + Sicherheit | Ultralytics YOLO (`yolo11n`), COCO-Klasse „cell phone“, Schwelle 0,5 |

- Die Kamera ist offen, sobald Webcam **oder** Smartphone aktiv ist. Beide werten
  dasselbe Bild aus. Der Face Landmarker läuft bei beiden (Kopfneigung braucht auch
  die Handy-Regel), YOLO nur bei aktivem Smartphone-Sensor.
- Checkboxen wirken sofort, auch während einer Session; jede Änderung wird protokolliert.
- Screenshots (`mss`) macht nicht der PC-Sensor dauernd, sondern der KI-Richter bei
  Bedarf.
- Sensoren laufen nur während einer Session. Ohne Session ist die Kamera aus und es
  wird nichts aufgezeichnet.

## 5. Entscheider

### 5.1 Listen

- **Globale Ablenkungs-Liste** in `settings.toml` (Programme und Domains).
- **Aufgabenbezogene Listen** (Fokus und Ablenkung, je Programme und Domains), pro
  Aufgabe in SQLite gespeichert. Schlüssel der Aufgabe: Aufgabentext, kleingeschrieben,
  Leerraum normalisiert. Gleicher Text = gleiche Listen und gleiches Gedächtnis.
- **Startlisten durch die KI:** Beim Start einer Session mit neuer Aufgabe erzeugt ein
  KI-Aufruf Vorschläge aus dem Aufgabentext. Gemischte Plattformen (YouTube, Reddit,
  X, Google) kommen auf keine Liste, damit sie seitenweise beurteilt werden. Die Person
  sieht und bearbeitet die Vorschläge im Startdialog.
- Abgleich: Programme ohne Groß-/Kleinschreibung, Domains inklusive Subdomains
  (`docs.blender.org` passt auf `blender.org`).

### 5.2 PC-Urteil (jede Sekunde)

1. Prozess oder Domain auf Fokus-Liste → **FOKUS** (`regel`).
2. Prozess oder Domain auf Ablenkungs-Liste (global oder Aufgabe) → **ABGELENKT** (`regel`).
3. Eintrag im Gedächtnis → dessen Status (`gedaechtnis`). Suchreihenfolge: Seite
   (Domain + Fenstertitel), dann Domain, dann Programm + Fenstertitel.
4. Sonst → **UNKLAR** und KI-Anfrage einreihen. Bis zur Antwort bleibt der Status UNKLAR.

### 5.3 Kamera-Urteil

- **Abwesend:** kein Gesicht seit mehr als 15 s → **ABWESEND** (nur wenn Webcam aktiv).
- **Handy, Kopf gesenkt:** Handy erkannt **und** Kopfneigung > 20° nach unten,
  mindestens 3 s durchgehend → **ABGELENKT**, Quelle `handy` (`lokal`, ohne KI).
- **Handy, Kopf oben:** Handy erkannt, Kopf nicht gesenkt, mindestens 3 s →
  **UNKLAR** und KI prüft das Webcam-Bild (höchstens einmal pro 60 s; das Urteil gilt
  60 s).
- Sonst kein Beitrag (neutral).

### 5.4 Gesamturteil

Priorität: **ABGELENKT > ABWESEND > UNKLAR > FOKUS**. ABGELENKT schlägt ABWESEND,
damit z. B. eine Serie, die vom Sofa aus läuft, trotzdem eskaliert.

### 5.5 Stichprobe

Alle 120 s schickt der KI-Richter Screenshots **aller Monitore** plus Webcam-Bild
(sofern aktiv). Urteilt die KI „abgelenkt“, folgt nach 30 s eine Nachprüfung; erst wenn
auch diese „abgelenkt“ ergibt, entsteht eine Ablenkung mit Quelle `stichprobe`, die ab
der ersten Stichprobe zählt. Weitere Nachprüfungen folgen alle 30 s, bis die KI etwas
anderes urteilt. Bei ABWESEND entfällt die Stichprobe.

## 6. KI-Richter

- **Modell:** `claude-haiku-5-5`, Aufwand niedrig, strukturierte Ausgabe per JSON-Schema.
  API-Schlüssel aus `ANTHROPIC_API_KEY`.
- **Aufrufarten**
  1. *Startlisten:* Aufgabentext → `{fokus_programme, fokus_domains,
     ablenkung_programme, ablenkung_domains}`.
  2. *Unklare Seite/Programm:* Aufgabe, Prozess, Fenstertitel, URL, Screenshot des
     Monitors mit dem Vordergrundfenster.
  3. *Handy-Prüfung:* Aufgabe, Webcam-Bild.
  4. *Stichprobe:* Aufgabe, Screenshots aller Monitore, Webcam-Bild.
- **Antwort (Aufrufe 2–4):**
  `{status: "fokus" | "abgelenkt" | "unklar", begruendung: str, sicherheit: 0..1,
  gilt_fuer: "seite" | "domain" | "programm"}`.
  Sicherheit unter 0,6 wird als „unklar“ behandelt. Urteile aus Aufruf 2 landen im
  Gedächtnis mit der Ebene aus `gilt_fuer`.
- **Bilder:** JPEG, Qualität 80; Screenshots auf 1280 px lange Kante, Webcam 640×480.
- **Ratenbegrenzung:** höchstens 2 Aufrufe pro Minute (Token-Bucket); der
  Startlisten-Aufruf ist davon ausgenommen. Vorrang:
  Handy-Prüfung > unklare Seite > Stichprobe. Überzählige Anfragen derselben Quelle
  werden zusammengefasst.
- **Fehler** (offline, Zeitüberschreitung 15 s, Ratenlimit, ungültige Antwort): Status
  bleibt UNKLAR, erneuter Versuch frühestens nach 30 s, Fehler wird protokolliert.
- **Kosten:** Token-Verbrauch jedes Aufrufs wird protokolliert; die Auswertung zeigt
  eine Kostenschätzung pro Session.
- **Bilder speichern** (Schalter, Standard aus): legt die gesendeten Bilder mit dem
  Urteil im Datenordner ab, um Urteile nachzuprüfen.

## 7. Eskalation

Gemessen ab Beginn eines durchgehenden ABGELENKT-Gesamtstatus – egal, ob die Quelle
dazwischen wechselt. Wer von Instagram zu TikTok springt, setzt die Uhr also nicht
zurück. Aktionen der Stufe 3 richten sich gegen die jeweils aktuelle Quelle:

| Dauer | Stufe | Aktion |
|---|---|---|
| < 10 s | 0 | nichts (Gnadenfrist) |
| 10 s | 1 · Hinweis | Windows-Benachrichtigung + dezenter Ton; Icon gelb |
| 40 s | 2 · Overlay | Vollbild-Overlay über allen Monitoren; Icon rot |
| 70 s | 3 · Sperre | Quelle bis Session-Ende gesperrt |

- **Rückfall:** Beginnt innerhalb von 5 min nach Ende der letzten Ablenkung eine neue,
  läuft alles eine Stufe höher (10 s → Stufe 2, 40 s → Stufe 3).
- **Zurücksetzen:** 5 min durchgehend FOKUS löschen das Rückfall-Gedächtnis.
- **Ende einer Ablenkung:** Wechselt der Gesamtstatus von ABGELENKT auf irgendeinen
  anderen Status, endet die Ablenkung; ein offenes Overlay schließt sich.
- **Quelle `stichprobe`:** höchstens Stufe 2, weil sich nichts Konkretes sperren lässt.
  Die Ablenkung beginnt mit der ersten Stichprobe, die „abgelenkt“ ergab, und dauert,
  bis eine Nachprüfung (alle 30 s) etwas anderes ergibt.
- **Quelle `handy`:** Stufe 3 heißt Handy-Overlay („Leg das Handy weg“), das stehen
  bleibt, bis 5 s lang kein Handy im Bild ist.
- **Abwesenheit:** eskaliert nie. Bei Rückkehr nach mindestens 5 min Abwesenheit:
  Begrüßung („Du warst 7 Minuten weg. Weiter mit Blender?“).

### 7.1 Overlay

- Zeigt Aufgabe, bisherige Fokuszeit, erkannte Ablenkung mit Begründung.
- **„Zurück zur Aufgabe“** (oder Esc): schließt das Overlay. Ist die Quelle nach 5 s
  noch aktiv, läuft die Eskalation weiter.
- **„Gehört zur Aufgabe“:** Korrektur. Die Quelle kommt auf die Fokus-Liste der Aufgabe
  (Seite → Gedächtnis-Eintrag „fokus“, Domain/Programm → Fokus-Liste), die Eskalation
  endet. Bei `handy` wird die Handy-Erkennung 2 min ausgesetzt (z. B. für eine
  Zwei-Faktor-Anmeldung). Bei `stichprobe` wird das Urteil verworfen und die nächste
  reguläre Stichprobe abgewartet. Jede Korrektur wird protokolliert.

### 7.2 Sperre (`blocker.py`, ohne Admin-Rechte)

- **Programm:** Sobald ein gesperrtes Programm in den Vordergrund kommt, wird sein
  Fenster minimiert.
- **Domain:** Ist eine gesperrte Domain im aktiven Browser-Tab, sendet die App Strg+W an
  den Browser (Tab schließen).
- **Nie gesperrt** werden Programme der Liste `nie_sperren` (Standard: `explorer.exe`,
  `taskmgr.exe`, `python.exe`, `pythonw.exe`) und alles auf der Fokus-Liste.
- **„Sperren aufheben“** im Tray hebt alle Sperren der Session auf (protokolliert).

## 8. Oberfläche

- **Tray-Icon:** grau (keine Session), grün (Stufe 0, auch während der Gnadenfrist),
  gelb (Stufe 1), rot (Stufe 2/3), blau (ABWESEND). Tooltip: Aufgabe, Restzeit, Sensorprobleme.
- **Tray-Menü:** Session starten … · Session beenden · ☑ PC · ☑ Webcam · ☑ Smartphone ·
  Sperren aufheben · Einstellungen … · Auswertung … · Beenden
- **Startdialog:** Aufgabe (Text), Dauer (25 / 50 / 90 min oder frei), vorgeschlagene
  Listen als bearbeitbare Textfelder (ein Eintrag pro Zeile). Ohne KI bleiben die
  Felder leer und können von Hand gefüllt werden.
- **Session-Ende:** Bei Ablauf der Zeit Benachrichtigung „Session geschafft“ und
  Auswertung. „Session beenden“ oder „Beenden“ im Tray beendet sofort und vermerkt
  „vorzeitig beendet nach X von Y min“.
- **Auswertung:** letzte Session plus Tabelle der letzten 7 Tage (siehe 9.2).
- **Einstellungen …:** öffnet `settings.toml` im Standard-Editor; die App lädt die
  Datei beim Speichern neu. Checkboxen bleiben im Tray-Menü.

## 9. Daten

Ablage im Ordner `%APPDATA%\FocusGuard\`.

### 9.1 `settings.toml` (Standardwerte)

```toml
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
```

### 9.2 SQLite `focusguard.db`

| Tabelle | Inhalt |
|---|---|
| `sessions` | id, aufgabe, aufgabe_key, start, geplant_min, ende, vorzeitig_beendet, sensoren |
| `ereignisse` | id, session_id, zeit, art, quelle, status, details (JSON). Arten: `statuswechsel`, `ki_aufruf` (mit Tokens), `eskalation`, `sperre`, `sperre_aufgehoben`, `korrektur`, `sensor_fehler`, `checkbox`, `abwesenheit` |
| `gedaechtnis` | aufgabe_key, ebene (`seite`/`domain`/`programm`), schluessel, status, begruendung, sicherheit, zeit |
| `listen` | aufgabe_key, art (`fokus`/`ablenkung`), typ (`programm`/`domain`), wert |

Protokolliert werden Statuswechsel, nicht jede Sekunde. Die Auswertung berechnet
Zeitanteile aus den Statuswechseln:

- Minuten je Status (Fokus, Unklar, Abgelenkt, Abwesend)
- **Fokusquote** = Fokus-Zeit ÷ anwesende Zeit
- Top 5 Ablenkungen (Quelle, Anzahl, Dauer), Eskalationen je Stufe, Sperren und
  Aufhebungen, Korrekturen
- KI-Aufrufe und geschätzte Kosten
- vorzeitig beendet ja/nein

## 10. Fehlerbehandlung

| Fall | Verhalten |
|---|---|
| Kamera nicht verfügbar oder belegt | Webcam- und Smartphone-Sensor pausieren, neuer Versuch alle 30 s; Tooltip zeigt das Problem; PC-Sensor läuft weiter |
| KI nicht erreichbar, Limit, ungültige Antwort | Status bleibt UNKLAR, keine Eskalation, neuer Versuch frühestens nach 30 s |
| `ANTHROPIC_API_KEY` fehlt | Hinweis beim Start; App läuft nur mit Regeln (unklare Fälle bleiben UNKLAR) |
| URL nicht auslesbar | Urteil über Prozess und Fenstertitel |
| Sensor-Thread stürzt ab | Fehler protokollieren, Sensor nach 5 s neu starten; nach 3 Abstürzen in 5 min bleibt er aus und das Tooltip meldet es |
| Strg+W/Minimieren schlägt fehl | protokollieren, Overlay bleibt als Rückfall |
| Overlay | immer per Knopf oder Esc schließbar; „Beenden“ im Tray funktioniert immer |

## 11. Tests

- **Automatisch (pytest, läuft unter Linux und Windows):**
  - `rules`, `memory`, `judge`: Listenabgleich inkl. Subdomains, Suchreihenfolge im
    Gedächtnis, Prioritäten des Gesamturteils, Handy-Regeln, Abwesenheit.
  - `escalation`: Stufen nach 10/40/70 s, Rückfall, Zurücksetzen, Sonderfälle `handy`
    und `stichprobe`, Begrüßung – mit Test-Uhr.
  - Szenario-Tests: aufgezeichnete Beobachtungsfolgen rein, erwartete Aktionen raus
    (z. B. „30 s Instagram“ → Stufe 1 bei 10 s, keine Stufe 2).
  - `ai/client`: mit simuliertem Client – Schema-Prüfung, Sicherheitsschwelle,
    Ratenbegrenzung, Fehlerfälle.
  - `storage`, `config`: mit temporären Dateien.
- **KI-Qualität (manuell):** kleine Sammlung echter Screenshots und Webcam-Bilder mit
  erwartetem Urteil; ein Skript schickt sie an Haiku und zeigt Treffer und Fehler.
- **Windows (manuell, durch die Person):** Checkliste im README – Tray, Startdialog,
  PC-Sensor mit Chrome/Edge/Firefox, Webcam, Handy-Erkennung, Overlay auf mehreren
  Monitoren, Sperre per Minimieren und Strg+W, Auswertung.

Einschränkung: Die Entwicklung läuft in einem Linux-Container. Windows-spezifische
Teile werden dort nur über Schnittstellen mit Attrappen getestet; echte Tests auf
Windows macht die Person.

## 12. Technik

Python 3.12 · PySide6 · opencv-python · mediapipe · ultralytics · mss · pywin32 ·
psutil · uiautomation · anthropic · tomli-w · pytest

## 13. Spätere Ausbaustufen

1. Handy-App für Android, die die aktive App an den PC meldet (neuer Sensor am
   Entscheider).
2. Sperren mit Admin-Rechten (hosts-Datei).
3. Einstellungsdialog statt TOML-Datei.
4. Lokale Bild-KI als Alternative zur Cloud.
5. Produktreife: Installer, Datenschutz, weitere Plattformen.
