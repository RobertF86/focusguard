# FocusGuard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build version 1 of FocusGuard, a Windows tray app that watches PC, webcam and phone use during a focus session and escalates distractions in stages.

**Architecture:** One Python process. Sensors run in threads and push observations into a queue. A Qt timer drains the queue on the main thread every 250 ms and feeds the pure logic: Entscheider (rules, memory, camera rules, AI requests) → Eskalation (stages) → actions. The `Steuerung` executes those actions through ports (UI, blocker, AI judge, storage), so all logic is testable on Linux with fakes. The AI judge runs in its own worker thread and calls Claude Haiku 5.5.

**Tech Stack:** Python ≥ 3.12, PySide6-Essentials, MediaPipe Tasks (FaceLandmarker, ObjectDetector), opencv-contrib-python, numpy, mss, psutil, pywin32 + uiautomation (Windows only), anthropic SDK 2.x, SQLite (stdlib), pytest.

**Spec:** `docs/superpowers/specs/2026-10-21-focusguard-design.md`

## Global Constraints

- Code lives in `FocusGuard/` at the repo root; package `FocusGuard/focusguard/`, tests `FocusGuard/tests/`. All commands below run from `FocusGuard/` with the venv active.
- Identifiers, user-facing text and log text are German; user-facing text addresses the person with "du".
- Logic modules must import and test on Linux. `win32*`, `uiautomation`, `mediapipe`, `mss`, `winsound` are imported **inside** the functions/classes that need them, never at module top level. Exception: `numpy`/`cv2` may be top-level in `capture.py`, `sensors/gesicht.py`, `sensors/handy.py`, `sensors/kamera.py`.
- AI model `claude-haiku-5-5`, `output_config.effort = "low"`, structured output via `output_config.format` JSON schema, `max_tokens = 2048`. Never send `temperature`, `top_p`, `top_k`. API key only from environment (`anthropic.Anthropic()` default resolution).
- Data folder: `%APPDATA%\FocusGuard\` on Windows, `~/.focusguard/` elsewhere; `FOCUSGUARD_HOME` overrides both.
- The app must always be quittable immediately; the overlay is always closable by button or Esc; no admin rights anywhere.
- All times are wall-clock seconds (`time.time()`), injected as `uhr: Callable[[], float]`.
- Commit messages end with the two lines:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01SsN4ZFzov2GerbBio65DQH`
- Work on branch `claude/serene-hamilton-sjzb16`.

**Deliberate deviations from the spec (decided while planning):**

1. Phone detection uses MediaPipe ObjectDetector (EfficientDet-Lite0, COCO class "cell phone") instead of Ultralytics YOLO: avoids a ~2 GB PyTorch install and the `opencv-python`/`opencv-contrib-python` conflict between Ultralytics and MediaPipe.
2. Head-down is measured relative to a per-session baseline (median pitch of the first 20 face observations), so camera height does not matter.
3. Tray checkbox changes are written back into `settings.toml` by replacing only that line (comments survive); `tomli-w` is dropped.
4. Rule order inside 5.2 is specific-before-general: domain-fokus, domain-ablenkung, prozess-fokus, prozess-ablenkung (so `chrome.exe` on a focus list does not whitelist Instagram).
5. An AI verdict "unklar" for a page is re-asked at the earliest after 300 s.
6. Settings changes from `settings.toml` apply from the next session; tray checkboxes apply immediately.
7. Absence time is derived from `statuswechsel` events; there is no separate `abwesenheit` event type.

## Fixed constants (not in settings)

| Constant | Value | Owner |
|---|---|---|
| retry after AI error | 30 s | `decision/judge.py`, `decision/kamera_regeln.py` |
| retry after AI "unklar" (page) | 300 s | `decision/judge.py` |
| PC observation stale after | 5 s | `decision/judge.py` |
| phone detection gap tolerance | 1 s | `decision/kamera_regeln.py` |
| webcam stale after (no frames) | 3 s | `decision/kamera_regeln.py` |
| face counts as present for phone rules | seen within last 1 s | `decision/kamera_regeln.py` |
| head baseline | median of first 20 face pitches | `decision/kamera_regeln.py` |
| phone suspension after correction | 120 s | `decision/judge.py` |
| phone overlay closes after phone-free | 5 s | `escalation.py` |
| overlay re-show pause after "Zurück" | 5 s | `escalation.py` |
| blocker cooldown | 2 s | `blocker.py` |
| sensor restart wait / crash limit | 5 s / 3 crashes in 300 s | `sensors/base.py` |
| camera reopen interval | 30 s | `sensors/kamera.py` |
| phone score threshold | 0.5 | `sensors/handy.py` |
| AI request timeout | 15 s, `max_retries=0` | `ai/client.py` |
| Qt tick | 250 ms | `app.py` |
| PC sensor / camera sensor interval | 1.0 s / 0.5 s | `sensors/verwaltung.py` |

## Review Focus

1. FocusGuard's own windows (overlay, dialogs, report) in the foreground must never be judged, sent to the AI or blocked → Task 11 `test_pc_sensor_ignoriert_eigenes_fenster`.
2. The camera stops delivering frames mid-session (Teams grabs it, cable pulled) → no ABWESEND, no greeting, no escalation → Task 5 `test_kein_abwesend_wenn_keine_bilder_mehr_kommen`.
3. Ctrl+W fires again before the browser has updated its title → must not close a second tab → Task 13 `test_blocker_cooldown_2_s`, `test_blocker_tab_nur_wenn_fenster_noch_vorne`.
4. The AI returns garbage, refuses, hits `max_tokens`, or the network is down → status stays UNKLAR, no escalation, no request storm → Task 8 `test_parse_urteil_ungueltig_wirft`, Task 9 `test_anthropic_sender_refusal_und_max_tokens`, Task 6 `test_ki_fehler_erneut_frueh_nach_30_s`.
5. The session ends (time up or early) while an overlay is open or blocks are active → overlay closes, blocks lifted, sensors stopped → Task 15 `test_vorzeitig_beenden_schliesst_overlay_und_hebt_sperren_auf`.

---

### Task 1: Project skeleton, models, clock, settings

**Files:**
- Create: `FocusGuard/pyproject.toml`, `FocusGuard/.gitignore`, `FocusGuard/focusguard/__init__.py`, `FocusGuard/focusguard/models.py`, `FocusGuard/focusguard/clock.py`, `FocusGuard/focusguard/config.py`
- Test: `FocusGuard/tests/test_models.py`, `FocusGuard/tests/test_config.py`

**Interfaces:**
- Produces (`models.py`):
  - `class Status(StrEnum)`: `FOKUS="fokus"`, `UNKLAR="unklar"`, `ABGELENKT="abgelenkt"`, `ABWESEND="abwesend"`
  - frozen dataclasses:
    `PcBeobachtung(zeit: float, fenster_id: int, prozess: str, fenstertitel: str, url: str | None, domain: str | None, ist_browser: bool)`,
    `WebcamBeobachtung(zeit: float, gesicht: bool, kopf_pitch_grad: float | None)`,
    `HandyBeobachtung(zeit: float, handy_erkannt: bool, sicherheit: float)`,
    `Urteil(status: Status, quelle: str, begruendung: str, herkunft: str, seit: float | None = None)` (herkunft ∈ `"regel"`, `"gedaechtnis"`, `"ki"`, `"lokal"`),
    `AufgabenListen(fokus_programme: tuple[str, ...] = (), fokus_domains: tuple[str, ...] = (), ablenkung_programme: tuple[str, ...] = (), ablenkung_domains: tuple[str, ...] = ())` with methods `mit_fokus_domain(d: str) -> AufgabenListen`, `mit_fokus_programm(p: str) -> AufgabenListen` (no duplicates) and `ist_leer() -> bool`,
    `GedaechtnisEintrag(aufgabe_key: str, ebene: str, schluessel: str, status: Status, begruendung: str, sicherheit: float, zeit: float)` (ebene ∈ `"seite"`, `"domain"`, `"programm"`),
    `KiUrteil(status: Status, begruendung: str, sicherheit: float, gilt_fuer: str)`,
    `KiAnfrage(art: KiArt, quelle: str, zeit: float, pc: PcBeobachtung | None, mit_bildschirm: bool, mit_webcam: bool)` with property `prioritaet -> int`,
    `KiErgebnis(anfrage: KiAnfrage, urteil: KiUrteil | None, fehler: str | None, tokens_ein: int = 0, tokens_aus: int = 0)`,
    actions `Hinweis(text: str)`, `OverlayZeigen(text: str, quelle: str)`, `OverlaySchliessen()`, `Sperren(quelle: str)`, `HandyOverlay()`, `Begruessung(minuten_weg: int)`, `IconStatus(farbe: str)` (farbe ∈ `grau gruen gelb rot blau`), `Aktion = Hinweis | OverlayZeigen | …`,
    `Ereignis(zeit: float, art: str, quelle: str, status: str, details: dict)`.
  - mutable dataclass `Session(id: int | None, aufgabe: str, aufgabe_key: str, start: float, geplant_min: int, ende: float | None = None, vorzeitig_beendet: bool = False)`
  - `class KiArt(StrEnum)`: `SEITE="seite"`, `HANDY="handy"`, `STICHPROBE="stichprobe"`; `KiAnfrage.prioritaet`: HANDY 0, SEITE 1, STICHPROBE 2 (lower first)
  - `aufgabe_key(text: str) -> str`, `quelle_domain(d) -> "domain:<d>"`, `quelle_prozess(p) -> "prozess:<p>"`, `quelle_seite(schluessel) -> "seite:<schluessel>"`, `QUELLE_HANDY = "handy"`, `QUELLE_STICHPROBE = "stichprobe"`
- Produces (`clock.py`): `Uhr = Callable[[], float]`, `echte_uhr = time.time`, `class TestUhr(start: float = 0.0)` with `__call__() -> float`, `vor(sekunden: float) -> None`, `setze(t: float) -> None`
- Produces (`config.py`): frozen dataclasses `SensorEinst(pc, webcam, smartphone)`, `KiEinst(modell, max_aufrufe_pro_minute, stichprobe_sekunden, stichprobe_nachpruefung_sekunden, handy_pruefung_sekunden, min_sicherheit, bilder_speichern)`, `ErkennungEinst(handy_mindestdauer_sekunden, kopf_gesenkt_grad, abwesend_nach_sekunden, begruessung_ab_minuten)`, `EskalationEinst(stufe1_sekunden, stufe2_sekunden, stufe3_sekunden, rueckfall_fenster_minuten, reset_nach_fokus_minuten)`, `ListenEinst(ablenkung_domains: tuple, ablenkung_programme: tuple, nie_sperren: tuple)`, `Einstellungen(sensoren, ki, erkennung, eskalation, listen)` — all field defaults = spec 9.1; `STANDARD_TOML: str` (spec 9.1 text verbatim); `class EinstellungsFehler(Exception)`; `lade_einstellungen(pfad: Path) -> Einstellungen`; `setze_sensor(pfad: Path, name: str, wert: bool) -> None`; `datenordner() -> Path`

- [ ] **Step 1: Create `pyproject.toml` and `.gitignore`, set up the venv**

`pyproject.toml`: setuptools build, `name = "focusguard"`, `version = "0.1.0"`, `requires-python = ">=3.12"`, dependencies
`anthropic>=2.1,<3`, `PySide6-Essentials>=6.12,<7`, `mediapipe>=1.1,<2`, `opencv-contrib-python>=4.10`, `numpy`, `mss>=10`, `psutil>=7`, `pywin32>=312; sys_platform == 'win32'`, `uiautomation>=2.0; sys_platform == 'win32'`; extra `dev = ["pytest>=9"]`; `[tool.pytest.ini_options] testpaths = ["tests"]`; packages `focusguard*`.
`.gitignore`: `.venv/`, `__pycache__/`, `*.egg-info/`, `.pytest_cache/`.

Run: `cd FocusGuard && python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"`
Expected: install succeeds (on Linux the two Windows-only packages are skipped).

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_models.py
from focusguard.models import aufgabe_key, quelle_domain, quelle_prozess, quelle_seite, AufgabenListen, KiAnfrage, KiArt
from focusguard.clock import TestUhr

def test_aufgabe_key_normalisiert():
    assert aufgabe_key("  Blender   Grundlagen\tLernen ") == "blender grundlagen lernen"

def test_quellen_format():
    assert quelle_domain("instagram.com") == "domain:instagram.com"
    assert quelle_prozess("steam.exe") == "prozess:steam.exe"
    assert quelle_seite("youtube.com|Titel") == "seite:youtube.com|Titel"

def test_listen_ergaenzen_ohne_duplikate():
    l = AufgabenListen(fokus_domains=("blender.org",))
    assert l.mit_fokus_domain("blender.org").fokus_domains == ("blender.org",)
    assert l.mit_fokus_programm("blender.exe").fokus_programme == ("blender.exe",)
    assert AufgabenListen().ist_leer() and not l.ist_leer()

def test_prioritaet():
    p = lambda art: KiAnfrage(art, "q", 0.0, None, True, True).prioritaet
    assert p(KiArt.HANDY) < p(KiArt.SEITE) < p(KiArt.STICHPROBE)

def test_test_uhr():
    u = TestUhr(100.0); u.vor(2.5)
    assert u() == 102.5
```

```python
# tests/test_config.py
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
    p = tmp_path / "settings.toml"; p.write_text("[eskalation]\nstufe1_sekunden = 5\nunbekannt = 1\n")
    e = lade_einstellungen(p)
    assert e.eskalation.stufe1_sekunden == 5 and e.eskalation.stufe2_sekunden == 40 and e.sensoren.pc is True

def test_ungueltiges_toml_wirft(tmp_path):
    p = tmp_path / "settings.toml"; p.write_text("[ki\nmodell = ")
    with pytest.raises(EinstellungsFehler):
        lade_einstellungen(p)

def test_falscher_typ_nennt_schluessel(tmp_path):
    p = tmp_path / "settings.toml"; p.write_text('[eskalation]\nstufe1_sekunden = "zehn"\n')
    with pytest.raises(EinstellungsFehler, match="stufe1_sekunden"):
        lade_einstellungen(p)

def test_setze_sensor_aendert_nur_diese_zeile(tmp_path):
    p = tmp_path / "settings.toml"; lade_einstellungen(p)
    setze_sensor(p, "webcam", False)
    text = p.read_text()
    assert "webcam = false" in text and "# zugleich die Gnadenfrist" in text
    assert lade_einstellungen(p).sensoren.webcam is False

def test_datenordner_focusguard_home(monkeypatch, tmp_path):
    monkeypatch.setenv("FOCUSGUARD_HOME", str(tmp_path / "fg"))
    assert datenordner() == tmp_path / "fg" and (tmp_path / "fg").is_dir()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_models.py tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'focusguard.models'`

- [ ] **Step 4: Implement `models.py`, `clock.py`, `config.py`**

`lade_einstellungen`: write `STANDARD_TOML` if the file is missing; parse with `tomllib`; for each section/field present, check the type against the default's type (`bool` must not pass as `int`; lists become tuples; an `int` is accepted for a `float` field) and raise `EinstellungsFehler(f"{abschnitt}.{schluessel}: …")` on mismatch; `tomllib.TOMLDecodeError` → `EinstellungsFehler`. `setze_sensor`: regex-replace `^(name)\s*=\s*(true|false)` inside the `[sensoren]` block only. `datenordner`: `FOCUSGUARD_HOME`, else `%APPDATA%\FocusGuard` on `win32`, else `~/.focusguard`; `mkdir(parents=True, exist_ok=True)`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add FocusGuard
git commit -m "feat(focusguard): project skeleton, models, clock and settings"
```

---

### Task 2: Storage (SQLite)

**Files:**
- Create: `FocusGuard/focusguard/storage.py`
- Test: `FocusGuard/tests/test_storage.py`

**Interfaces:**
- Consumes: `Session`, `Ereignis`, `GedaechtnisEintrag`, `AufgabenListen`, `Status` (Task 1)
- Produces: `class Speicher(pfad: Path | str)` (`":memory:"` allowed; creates schema of spec 9.2; tables `sessions`, `ereignisse`, `gedaechtnis` with unique `(aufgabe_key, ebene, schluessel)`, `listen`) with methods
  `neue_session(s: Session) -> int`, `beende_session(session_id: int, ende: float, vorzeitig: bool) -> None`, `sessions_seit(zeit: float) -> list[Session]` (ordered by start), `ereignis(session_id: int, zeit: float, art: str, quelle: str = "", status: str = "", details: dict | None = None) -> None`, `ereignisse(session_id: int) -> list[Ereignis]` (ordered by zeit, then id), `lade_gedaechtnis(aufgabe_key: str) -> list[GedaechtnisEintrag]`, `speichere_gedaechtnis(e: GedaechtnisEintrag) -> None` (upsert), `lade_listen(aufgabe_key: str) -> AufgabenListen`, `speichere_listen(aufgabe_key: str, listen: AufgabenListen) -> None` (replaces all rows for that key), `schliesse() -> None`.
  Only used from the Qt main thread.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_storage.py
from focusguard.storage import Speicher
from focusguard.models import Session, GedaechtnisEintrag, AufgabenListen, Status

def test_session_anlegen_und_beenden():
    s = Speicher(":memory:")
    sid = s.neue_session(Session(None, "Blender", "blender", 1000.0, 50))
    s.beende_session(sid, 1600.0, True)
    [x] = s.sessions_seit(0)
    assert (x.id, x.ende, x.vorzeitig_beendet, x.geplant_min) == (sid, 1600.0, True, 50)

def test_ereignisse_reihenfolge_und_details():
    s = Speicher(":memory:"); sid = s.neue_session(Session(None, "a", "a", 0.0, 25))
    s.ereignis(sid, 2.0, "eskalation", "domain:x.com", "abgelenkt", {"stufe": 2})
    s.ereignis(sid, 1.0, "statuswechsel", "", "fokus")
    e = s.ereignisse(sid)
    assert [x.art for x in e] == ["statuswechsel", "eskalation"] and e[1].details == {"stufe": 2} and e[0].details == {}

def test_gedaechtnis_upsert():
    s = Speicher(":memory:")
    e1 = GedaechtnisEintrag("k", "seite", "youtube.com|T", Status.FOKUS, "passt", 0.9, 1.0)
    s.speichere_gedaechtnis(e1)
    s.speichere_gedaechtnis(GedaechtnisEintrag("k", "seite", "youtube.com|T", Status.ABGELENKT, "nein", 0.8, 2.0))
    [x] = s.lade_gedaechtnis("k")
    assert x.status is Status.ABGELENKT and s.lade_gedaechtnis("anders") == []

def test_listen_ersetzen_und_leer():
    s = Speicher(":memory:")
    s.speichere_listen("k", AufgabenListen(("blender.exe",), ("blender.org",), (), ()))
    s.speichere_listen("k", AufgabenListen((), ("docs.blender.org",), (), ("9gag.com",)))
    assert s.lade_listen("k") == AufgabenListen((), ("docs.blender.org",), (), ("9gag.com",))
    assert s.lade_listen("neu") == AufgabenListen()

def test_datei_bleibt_erhalten(tmp_path):
    p = tmp_path / "fg.db"; s = Speicher(p); s.neue_session(Session(None, "a", "a", 0.0, 25)); s.schliesse()
    assert len(Speicher(p).sessions_seit(0)) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_storage.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `Speicher` in `storage.py`** (`sqlite3`, details as JSON text, commit after each write)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_storage.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add FocusGuard/focusguard/storage.py FocusGuard/tests/test_storage.py
git commit -m "feat(focusguard): SQLite storage for sessions, events, memory and lists"
```

---

### Task 3: Rules

**Files:**
- Create: `FocusGuard/focusguard/decision/__init__.py`, `FocusGuard/focusguard/decision/rules.py`, `FocusGuard/tests/hilfen.py`
- Test: `FocusGuard/tests/test_rules.py`

**Interfaces:**
- Consumes: `PcBeobachtung`, `AufgabenListen`, `Urteil`, `Status`, `quelle_*` (Task 1); `ListenEinst` (Task 1)
- Produces (`rules.py`):
  - `BROWSER_PROZESSE = frozenset({"chrome.exe", "msedge.exe", "brave.exe", "firefox.exe", "opera.exe", "vivaldi.exe"})`
  - `domain_aus_url(url: str | None) -> str | None` — lowercase host without `www.`, works without scheme; `None` for empty, `None`-input or non-http(s) schemes like `chrome://`
  - `domain_passt(domain: str, liste: Iterable[str]) -> bool` — equal or subdomain
  - `programm_passt(prozess: str, liste: Iterable[str]) -> bool` — case-insensitive equality
  - `regel_urteil(b: PcBeobachtung, aufgabe: AufgabenListen, global_listen: ListenEinst) -> Urteil | None` — order: domain-fokus → domain-ablenkung (aufgabe + global) → prozess-fokus → prozess-ablenkung (aufgabe + global); quelle uses the **matching list entry**; herkunft `"regel"`; begruendung e.g. `"instagram.com steht auf der Ablenkungs-Liste"` / `"blender.exe gehört zur Aufgabe"`
- Produces (`tests/hilfen.py`): `pc(prozess="chrome.exe", titel="", url=None, zeit=0.0, fenster_id=1) -> PcBeobachtung` (domain via `domain_aus_url`, `ist_browser` via `BROWSER_PROZESSE`), `einst(**ueberschreibungen) -> Einstellungen` (defaults)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rules.py
import pytest
from focusguard.decision.rules import domain_aus_url, domain_passt, programm_passt, regel_urteil
from focusguard.models import AufgabenListen, Status
from hilfen import pc, einst

@pytest.mark.parametrize("url,erwartet", [
    ("https://www.youtube.com/watch?v=1", "youtube.com"), ("youtube.com/watch?v=1", "youtube.com"),
    ("HTTP://Docs.Blender.org/manual", "docs.blender.org"), ("localhost:8080/x", "localhost"),
    ("chrome://newtab", None), ("", None), (None, None)])
def test_domain_aus_url(url, erwartet):
    assert domain_aus_url(url) == erwartet

def test_domain_und_programm_passt():
    assert domain_passt("docs.blender.org", ["blender.org"]) and domain_passt("blender.org", ["blender.org"])
    assert not domain_passt("notblender.org", ["blender.org"])
    assert programm_passt("Blender.EXE", ["blender.exe"]) and not programm_passt("blender2.exe", ["blender.exe"])

def test_regel_reihenfolge():
    g = einst().listen
    aufgabe = AufgabenListen(fokus_programme=("chrome.exe",), fokus_domains=("blender.org",))
    u = regel_urteil(pc(url="https://www.instagram.com/"), aufgabe, g)
    assert (u.status, u.quelle, u.herkunft) == (Status.ABGELENKT, "domain:instagram.com", "regel")
    assert regel_urteil(pc(url="https://docs.blender.org/x"), aufgabe, g).quelle == "domain:blender.org"
    assert regel_urteil(pc(url="https://example.org"), aufgabe, g).quelle == "prozess:chrome.exe"
    assert regel_urteil(pc("steam.exe"), AufgabenListen(), g).quelle == "prozess:steam.exe"
    assert regel_urteil(pc("notepad.exe"), AufgabenListen(), g) is None

def test_aufgaben_fokus_schlaegt_globale_ablenkung():
    u = regel_urteil(pc(url="https://instagram.com"), AufgabenListen(fokus_domains=("instagram.com",)), einst().listen)
    assert u.status is Status.FOKUS
```

`tests/hilfen.py` is imported as a top-level module: add `pythonpath = ["tests"]` to `[tool.pytest.ini_options]`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_rules.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `rules.py` and `tests/hilfen.py`** (`urllib.parse.urlsplit`; prepend `http://` when no `://` present)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_rules.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add FocusGuard
git commit -m "feat(focusguard): focus/distraction list rules"
```

---

### Task 4: Memory of AI verdicts

**Files:**
- Create: `FocusGuard/focusguard/decision/memory.py`
- Test: `FocusGuard/tests/test_memory.py`

**Interfaces:**
- Consumes: `PcBeobachtung`, `KiUrteil`, `GedaechtnisEintrag`, `Status`, `quelle_*` (Task 1)
- Produces:
  - `seiten_schluessel(b: PcBeobachtung) -> str` = `f"{b.domain or b.prozess}|{b.fenstertitel}"`
  - `eintrag_fuer(b: PcBeobachtung, u: KiUrteil, aufgabe_key: str, zeit: float) -> GedaechtnisEintrag | None` — `None` for `Status.UNKLAR`; ebene from `u.gilt_fuer`; `"domain"` without `b.domain` → `"seite"`; `"programm"` when `b.ist_browser` → `"seite"`; schluessel: seite → `seiten_schluessel(b)`, domain → `b.domain`, programm → `b.prozess`
  - `quelle_fuer(e: GedaechtnisEintrag) -> str` — seite → `quelle_seite`, domain → `quelle_domain`, programm → `quelle_prozess`
  - `class Gedaechtnis(eintraege: Iterable[GedaechtnisEintrag] = ())` with `suche(b: PcBeobachtung) -> GedaechtnisEintrag | None` (seite → domain → programm; programm skipped for browsers) and `merke(e: GedaechtnisEintrag) -> None` (replaces same ebene+schluessel)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_memory.py
from focusguard.decision.memory import seiten_schluessel, eintrag_fuer, quelle_fuer, Gedaechtnis
from focusguard.models import KiUrteil, Status, GedaechtnisEintrag
from hilfen import pc

YT = pc(url="https://youtube.com/watch?v=1", titel="Blender Donut")

def test_seiten_schluessel():
    assert seiten_schluessel(YT) == "youtube.com|Blender Donut"
    assert seiten_schluessel(pc("blender.exe", titel="x")) == "blender.exe|x"

def test_eintrag_ebenen():
    assert eintrag_fuer(YT, KiUrteil(Status.FOKUS, "ok", 0.9, "domain"), "k", 1.0).schluessel == "youtube.com"
    assert eintrag_fuer(pc("firefox.exe", titel="T"), KiUrteil(Status.FOKUS, "ok", 0.9, "domain"), "k", 1.0).ebene == "seite"
    assert eintrag_fuer(YT, KiUrteil(Status.FOKUS, "ok", 0.9, "programm"), "k", 1.0).ebene == "seite"
    assert eintrag_fuer(pc("blender.exe"), KiUrteil(Status.FOKUS, "ok", 0.9, "programm"), "k", 1.0).schluessel == "blender.exe"
    assert eintrag_fuer(YT, KiUrteil(Status.UNKLAR, "?", 0.3, "seite"), "k", 1.0) is None

def test_suche_reihenfolge():
    g = Gedaechtnis([GedaechtnisEintrag("k", "domain", "youtube.com", Status.ABGELENKT, "", 0.9, 0),
                     GedaechtnisEintrag("k", "seite", "youtube.com|Blender Donut", Status.FOKUS, "", 0.9, 0)])
    assert g.suche(YT).status is Status.FOKUS
    assert g.suche(pc(url="https://youtube.com/x", titel="Katzen")).status is Status.ABGELENKT
    assert g.suche(pc(url="https://example.org")) is None

def test_quelle_fuer():
    mk = lambda ebene, s: GedaechtnisEintrag("k", ebene, s, Status.FOKUS, "", 1, 0)
    assert quelle_fuer(mk("seite", "a|b")) == "seite:a|b"
    assert quelle_fuer(mk("domain", "a.com")) == "domain:a.com"
    assert quelle_fuer(mk("programm", "a.exe")) == "prozess:a.exe"
```

- [ ] **Step 2: Run tests to verify they fail** — `python -m pytest tests/test_memory.py -v` → FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implement `memory.py`** (dict keyed by `(ebene, schluessel)`)

- [ ] **Step 4: Run tests to verify they pass** — `python -m pytest tests/test_memory.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add FocusGuard/focusguard/decision/memory.py FocusGuard/tests/test_memory.py
git commit -m "feat(focusguard): memory of AI verdicts per page, domain and program"
```

---

### Task 5: Camera rules (absence and phone)

**Files:**
- Create: `FocusGuard/focusguard/decision/kamera_regeln.py`
- Test: `FocusGuard/tests/test_kamera_regeln.py`

**Interfaces:**
- Consumes: `WebcamBeobachtung`, `HandyBeobachtung`, `Urteil`, `KiUrteil`, `Status`, `QUELLE_HANDY` (Task 1); `ErkennungEinst`, `KiEinst` (Task 1)
- Produces: `class KameraBewerter(erkennung: ErkennungEinst, handy_pruefung_sekunden: int, start: float, webcam_aktiv: bool, smartphone_aktiv: bool)` with
  `setze_aktiv(webcam: bool, smartphone: bool) -> None`, `webcam(b: WebcamBeobachtung) -> None`, `handy(b: HandyBeobachtung) -> None`,
  `urteil(jetzt: float) -> Urteil | None`, `braucht_ki(jetzt: float) -> bool`, `ki_angefragt(jetzt: float) -> None`, `ki_ergebnis(u: KiUrteil | None, jetzt: float) -> None`, `handy_aussetzen(bis: float) -> None`, `handy_frei_seit(jetzt: float) -> float` (seconds since the phone was last seen; large if never)

Rules (exact):
- ABWESEND: webcam aktiv **and** last WebcamBeobachtung ≤ 3 s old **and** no face for > `abwesend_nach_sekunden` (last face time starts at `start`).
- Baseline: median of `kopf_pitch_grad` of the first 20 observations with a face; until then 0. "Kopf gesenkt" = `pitch - baseline > kopf_gesenkt_grad`.
- Phone rules only when smartphone aktiv, not suspended, and a face was seen within the last 1 s. Phone run = consecutive positive HandyBeobachtungen with gaps ≤ 1 s.
- Phone run ≥ `handy_mindestdauer_sekunden` and head down for the last ≥ `handy_mindestdauer_sekunden` → `Urteil(ABGELENKT, "handy", "Handy in der Hand", "lokal")`.
- Phone run ≥ minimum, head up → valid AI verdict (≤ `handy_pruefung_sekunden` old) ABGELENKT → `Urteil(ABGELENKT, "handy", <begruendung>, "ki")`; FOKUS → `None`; otherwise `Urteil(UNKLAR, "handy", "Handy im Bild", "lokal")`.
- `braucht_ki`: the UNKLAR phone case holds and `jetzt >= naechste_anfrage`. `ki_angefragt` sets `naechste_anfrage = jetzt + handy_pruefung_sekunden`; `ki_ergebnis(None)` sets it to `jetzt + 30`.
- Priority inside `urteil`: phone ABGELENKT > ABWESEND > phone UNKLAR > `None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_kamera_regeln.py
from focusguard.decision.kamera_regeln import KameraBewerter
from focusguard.models import WebcamBeobachtung as W, HandyBeobachtung as H, KiUrteil, Status
from hilfen import einst

def kb(webcam=True, smartphone=True):
    e = einst()
    return KameraBewerter(e.erkennung, e.ki.handy_pruefung_sekunden, 0.0, webcam, smartphone)

def gesichter(k, von, bis, pitch=5.0, schritt=0.5):
    t = von
    while t <= bis:
        k.webcam(W(t, True, pitch)); t += schritt

def test_abwesend_nach_15_s_ohne_gesicht():
    k = kb(); k.webcam(W(0, True, 5))
    for t in range(1, 17): k.webcam(W(t, False, None))
    assert k.urteil(14.5) is None
    assert k.urteil(16.5).status is Status.ABWESEND

def test_kein_abwesend_wenn_webcam_aus():
    k = kb(webcam=False); k.webcam(W(0, True, 5))
    for t in range(1, 30): k.webcam(W(t, False, None))
    assert k.urteil(29.5) is None

def test_kein_abwesend_wenn_keine_bilder_mehr_kommen():
    k = kb(); k.webcam(W(0, True, 5))
    assert k.urteil(30) is None

def test_handy_kopf_gesenkt_nach_3_s():
    k = kb(); gesichter(k, 0, 10)                 # baseline 5
    for i in range(7):                            # 10.5 .. 13.5
        t = 10.5 + i * 0.5; k.webcam(W(t, True, 30)); k.handy(H(t, True, 0.8))
    assert k.urteil(12.5) is None or k.urteil(12.5).status is not Status.ABGELENKT
    u = k.urteil(13.5)
    assert (u.status, u.quelle, u.herkunft) == (Status.ABGELENKT, "handy", "lokal")

def test_handy_luecke_bis_1_s_unterbricht_nicht():
    k = kb(); gesichter(k, 0, 10)
    for t in (10.5, 11.5, 12.5, 13.5):
        k.webcam(W(t, True, 30)); k.handy(H(t, True, 0.8))
    assert k.urteil(13.5).status is Status.ABGELENKT

def test_baseline_relativ():
    k = kb(); gesichter(k, 0, 10, pitch=15)       # baseline 15
    for i in range(8):
        t = 10.5 + i * 0.5; k.webcam(W(t, True, 30)); k.handy(H(t, True, 0.8))
    assert k.urteil(14.0).status is Status.UNKLAR  # 30 - 15 < 20

def test_handy_kopf_oben_ki_hoechstens_alle_60_s():
    k = kb(); gesichter(k, 0, 10)
    for i in range(8):
        t = 10.5 + i * 0.5; k.webcam(W(t, True, 5)); k.handy(H(t, True, 0.8))
    assert k.urteil(14.0).status is Status.UNKLAR and k.braucht_ki(14.0)
    k.ki_angefragt(14.0)
    assert not k.braucht_ki(20.0)
    k.ki_ergebnis(KiUrteil(Status.ABGELENKT, "Du tippst auf dem Handy", 0.9, "seite"), 15.0)
    assert k.urteil(14.0).herkunft == "ki"

def test_ki_fehler_neuer_versuch_nach_30_s():
    k = kb(); gesichter(k, 0, 10)
    for i in range(8):
        t = 10.5 + i * 0.5; k.webcam(W(t, True, 5)); k.handy(H(t, True, 0.8))
    k.ki_angefragt(14.0); k.ki_ergebnis(None, 14.0)
    for i in range(70):
        t = 14.5 + i * 0.5; k.webcam(W(t, True, 5)); k.handy(H(t, True, 0.8))
    assert not k.braucht_ki(43.0) and k.braucht_ki(44.5)

def test_handy_aussetzen_und_ohne_gesicht():
    k = kb(); gesichter(k, 0, 10); k.handy_aussetzen(200.0)
    for i in range(8):
        t = 10.5 + i * 0.5; k.webcam(W(t, True, 30)); k.handy(H(t, True, 0.8))
    assert k.urteil(14.0) is None
    k2 = kb(); k2.handy(H(1, True, 0.9)); k2.handy(H(5, True, 0.9))
    assert k2.urteil(5) is None                    # no face → no phone rules

def test_handy_frei_seit():
    k = kb(); k.handy(H(10, True, 0.9)); k.handy(H(11, False, 0.1))
    assert k.handy_frei_seit(16) == 6
```

- [ ] **Step 2: Run tests to verify they fail** — `python -m pytest tests/test_kamera_regeln.py -v` → FAIL

- [ ] **Step 3: Implement `KameraBewerter`** (`statistics.median` for the baseline)

- [ ] **Step 4: Run tests to verify they pass** — `python -m pytest tests/test_kamera_regeln.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add FocusGuard/focusguard/decision/kamera_regeln.py FocusGuard/tests/test_kamera_regeln.py
git commit -m "feat(focusguard): camera rules for absence and phone use"
```

---

### Task 6: Entscheider

**Files:**
- Create: `FocusGuard/focusguard/decision/judge.py`
- Test: `FocusGuard/tests/test_judge.py`

**Interfaces:**
- Consumes: `regel_urteil` (Task 3), `Gedaechtnis`, `eintrag_fuer`, `quelle_fuer`, `seiten_schluessel` (Task 4), `KameraBewerter` (Task 5), models (Task 1)
- Produces: `class Entscheider(einst: Einstellungen, aufgabe_key: str, listen: AufgabenListen, gedaechtnis: Gedaechtnis, start: float)` with
  - attribute `kamera: KameraBewerter`; property `listen -> AufgabenListen`; property `letzte_pc -> PcBeobachtung | None`
  - `setze_sensoren(pc: bool, webcam: bool, smartphone: bool) -> None` (initial values from `einst.sensoren`)
  - `pc(b) / webcam(b) / handy(b) -> None`
  - `urteil(jetzt: float) -> Urteil` — combines PC (ignored if PC off or last observation > 5 s old), camera and confirmed Stichprobe; priority ABGELENKT > ABWESEND > UNKLAR > FOKUS; nothing → `Urteil(FOKUS, "", "", "lokal")`
  - `ki_anfragen(jetzt: float) -> list[KiAnfrage]` — only new, due requests
  - `ki_ergebnis(e: KiErgebnis, jetzt: float) -> GedaechtnisEintrag | None` — returns a new memory entry to persist
  - `korrektur(quelle: str, jetzt: float) -> tuple[AufgabenListen | None, GedaechtnisEintrag | None]` — returns what to persist

Behaviour:
- PC chain: `regel_urteil` → `gedaechtnis.suche` (herkunft `"gedaechtnis"`, quelle `quelle_fuer`) → `Urteil(UNKLAR, quelle_seite(seiten_schluessel(b)), "Noch nicht beurteilt", "lokal")`.
- SEITE request when the PC chain is UNKLAR, that quelle is not in flight, and its retry time has passed (error → +30 s, KI "unklar" → +300 s). `mit_bildschirm=True`, `mit_webcam=False`, `pc=b`.
- HANDY request when `kamera.braucht_ki(jetzt)` and none in flight; call `kamera.ki_angefragt(jetzt)`. `mit_bildschirm=False`, `mit_webcam=True`.
- Stichprobe state machine (`ruhig` → `verdacht` → `bestaetigt`): first due at `start + stichprobe_sekunden`; not while the combined status without Stichprobe is ABWESEND, not when PC, webcam and smartphone are all off. `mit_bildschirm = pc aktiv`, `mit_webcam = webcam oder smartphone aktiv`, `pc = letzte_pc`. Result "abgelenkt" in `ruhig` → `verdacht` (start = request zeit), next check `jetzt + stichprobe_nachpruefung_sekunden`; "abgelenkt" in `verdacht` → `bestaetigt`; other result → `ruhig`, next `jetzt + stichprobe_sekunden`; error → state kept, next `jetzt + 30`. In `bestaetigt` the combined verdict includes `Urteil(ABGELENKT, "stichprobe", <begruendung>, "ki", seit=<verdacht start>)`.
- `korrektur`: `domain:x` → `listen.mit_fokus_domain(x)`; `prozess:p` → `mit_fokus_programm(p)`; `seite:k` → `GedaechtnisEintrag(aufgabe_key, "seite", k, FOKUS, "Von dir als passend markiert", 1.0, jetzt)` merged into memory; `handy` → `kamera.handy_aussetzen(jetzt + 120)`; `stichprobe` → `ruhig`, next `jetzt + stichprobe_sekunden`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_judge.py
from focusguard.decision.judge import Entscheider
from focusguard.decision.memory import Gedaechtnis
from focusguard.models import (AufgabenListen, KiArt, KiErgebnis, KiUrteil, Status,
                               WebcamBeobachtung as W)
from hilfen import pc, einst

def ent(**kw):
    return Entscheider(einst(**kw), "blender", AufgabenListen(fokus_programme=("blender.exe",)), Gedaechtnis(), 0.0)

def ki(e, anfrage, status, t, sicherheit=0.9, gilt="seite"):
    return e.ki_ergebnis(KiErgebnis(anfrage, KiUrteil(status, "Grund", sicherheit, gilt), None, 100, 10), t)

def test_ohne_beobachtungen_fokus():
    assert ent().urteil(1).status is Status.FOKUS

def test_regel_ablenkung():
    e = ent(); e.pc(pc(url="https://instagram.com", zeit=1))
    assert e.urteil(1).quelle == "domain:instagram.com"

def test_unbekannte_seite_genau_eine_anfrage_und_gedaechtnis():
    e = ent(); e.pc(pc(url="https://example.org", titel="T", zeit=1))
    assert e.urteil(1).status is Status.UNKLAR
    [a] = e.ki_anfragen(1)
    assert (a.art, a.quelle, a.mit_bildschirm) == (KiArt.SEITE, "seite:example.org|T", True)
    e.pc(pc(url="https://example.org", titel="T", zeit=2)); assert e.ki_anfragen(2) == []
    eintrag = ki(e, a, Status.ABGELENKT, 3)
    assert eintrag.schluessel == "example.org|T"
    u = e.urteil(3); assert (u.status, u.herkunft) == (Status.ABGELENKT, "gedaechtnis")

def test_ki_fehler_erneut_frueh_nach_30_s():
    e = ent(); e.pc(pc(url="https://example.org", titel="T", zeit=1)); [a] = e.ki_anfragen(1)
    assert e.ki_ergebnis(KiErgebnis(a, None, "Netz weg", 0, 0), 2) is None
    for t in (20, 31): e.pc(pc(url="https://example.org", titel="T", zeit=t))
    assert e.urteil(31).status is Status.UNKLAR
    assert e.ki_anfragen(31) == [] and len(e.ki_anfragen(32.5)) == 1

def test_ki_unklar_erneut_nach_300_s():
    e = ent(); e.pc(pc(url="https://example.org", zeit=1)); [a] = e.ki_anfragen(1)
    assert ki(e, a, Status.UNKLAR, 2) is None
    seiten = lambda t: [x for x in e.ki_anfragen(t) if x.art is KiArt.SEITE]   # Stichproben are due too
    e.pc(pc(url="https://example.org", zeit=290)); assert seiten(290) == []
    e.pc(pc(url="https://example.org", zeit=303)); assert len(seiten(303)) == 1

def test_pc_veraltet_und_pc_aus():
    e = ent(); e.pc(pc(url="https://instagram.com", zeit=1))
    assert e.urteil(7).status is Status.FOKUS
    e.pc(pc(url="https://instagram.com", zeit=8)); e.setze_sensoren(False, True, True)
    assert e.urteil(8).status is Status.FOKUS

def test_abgelenkt_schlaegt_abwesend():
    e = ent(); e.webcam(W(0, True, 5))
    for t in range(1, 20): e.webcam(W(t, False, None))
    e.pc(pc(url="https://netflix.com", zeit=19))
    assert e.urteil(19).status is Status.ABGELENKT

def test_stichprobe_alle_120_s_mit_bestaetigung():
    e = ent(); e.pc(pc("blender.exe", zeit=119))
    assert e.ki_anfragen(119) == []
    [a] = e.ki_anfragen(120)
    assert a.art is KiArt.STICHPROBE and a.mit_bildschirm and a.mit_webcam
    ki(e, a, Status.ABGELENKT, 125)
    e.pc(pc("blender.exe", zeit=150)); assert e.urteil(150).status is Status.FOKUS
    assert e.ki_anfragen(150) == []
    e.pc(pc("blender.exe", zeit=155)); [b] = e.ki_anfragen(155)
    ki(e, b, Status.ABGELENKT, 156)
    u = e.urteil(156); assert (u.status, u.quelle, u.seit) == (Status.ABGELENKT, "stichprobe", 120)

def test_stichprobe_nachpruefung_negativ():
    e = ent(); [a] = e.ki_anfragen(120); ki(e, a, Status.ABGELENKT, 121)
    [b] = e.ki_anfragen(151); ki(e, b, Status.FOKUS, 152)
    assert e.ki_anfragen(271) == [] and len(e.ki_anfragen(272)) == 1

def test_keine_stichprobe_bei_abwesend():
    e = ent(); e.webcam(W(0, True, 5))
    for t in range(1, 121): e.webcam(W(t, False, None))
    assert [a for a in e.ki_anfragen(120) if a.art is KiArt.STICHPROBE] == []

def test_korrekturen():
    e = ent(); e.pc(pc(url="https://instagram.com", zeit=1))
    listen, eintrag = e.korrektur("domain:instagram.com", 1)
    assert "instagram.com" in listen.fokus_domains and eintrag is None
    assert e.urteil(1).status is Status.FOKUS
    listen, eintrag = e.korrektur("seite:example.org|T", 2)
    assert listen is None and (eintrag.ebene, eintrag.status) == ("seite", Status.FOKUS)
    assert e.korrektur("handy", 3) == (None, None)
```

- [ ] **Step 2: Run tests to verify they fail** — `python -m pytest tests/test_judge.py -v` → FAIL

- [ ] **Step 3: Implement `Entscheider`**

- [ ] **Step 4: Run tests to verify they pass** — `python -m pytest tests/test_judge.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add FocusGuard/focusguard/decision/judge.py FocusGuard/tests/test_judge.py
git commit -m "feat(focusguard): Entscheider combining rules, memory, camera and spot checks"
```

---

### Task 7: Escalation

**Files:**
- Create: `FocusGuard/focusguard/escalation.py`
- Test: `FocusGuard/tests/test_escalation.py`

**Interfaces:**
- Consumes: `Urteil`, `Status`, action classes, `QUELLE_HANDY`, `QUELLE_STICHPROBE` (Task 1); `EskalationEinst` (Task 1)
- Produces: `class Eskalation(e: EskalationEinst, begruessung_ab_minuten: int, start: float)` with property `stufe -> int`,
  `schritt(u: Urteil, jetzt: float) -> list[Aktion]`, `zurueck_zur_aufgabe(jetzt: float) -> list[Aktion]`, `korrektur(jetzt: float) -> list[Aktion]`

Behaviour:
- A run starts with the first ABGELENKT verdict at `min(jetzt, u.seit or jetzt)` and lasts while the verdict stays ABGELENKT (source may change). Target stage by duration: ≥ stufe1 → 1, ≥ stufe2 → 2, ≥ stufe3 → 3; plus 1 (max 3) if the run started ≤ `rueckfall_fenster_minuten` after the previous run ended; capped at 2 when the current quelle is `stichprobe`.
- On reaching a higher stage emit only that stage's actions: 1 → `Hinweis(u.begruendung)`; 2 → `OverlayZeigen(u.begruendung, u.quelle)`; 3 → `HandyOverlay()` for `handy`, otherwise `Sperren(u.quelle)`. At stage 3 every new non-handy quelle gets its own `Sperren` once.
- Icon: `IconStatus` only on change, initial state `gruen`; ABWESEND → `blau`; otherwise stage 0 → `gruen`, 1 → `gelb`, ≥ 2 → `rot`.
- Run ends on any non-ABGELENKT verdict: if an overlay is open → `OverlaySchliessen()`; stage → 0; record end time for relapse. Exception: after `HandyOverlay` the run ends only once 5 s have passed since the last ABGELENKT verdict.
- Relapse memory clears after `reset_nach_fokus_minuten` of continuous FOKUS/UNKLAR.
- `zurueck_zur_aufgabe`: `[OverlaySchliessen()]`; while still ABGELENKT, re-emit `OverlayZeigen` for stage ≥ 2 at the earliest 5 s later (also for `HandyOverlay`).
- `korrektur`: ends the run without counting it as relapse: `[OverlaySchliessen()]` if open, then `IconStatus("gruen")` if changed.
- Greeting: transition from ABWESEND to another status after ≥ `begruessung_ab_minuten` → `Begruessung(int(dauer // 60))`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_escalation.py
from focusguard.escalation import Eskalation
from focusguard.models import (Urteil, Status, Hinweis, OverlayZeigen, OverlaySchliessen, Sperren,
                               HandyOverlay, Begruessung, IconStatus)
from hilfen import einst

ABG = lambda q="domain:instagram.com", seit=None: Urteil(Status.ABGELENKT, q, "Instagram", "regel", seit)
FOK = Urteil(Status.FOKUS, "", "", "lokal")
WEG = Urteil(Status.ABWESEND, "", "", "lokal")

def esk():
    e = einst(); return Eskalation(e.eskalation, e.erkennung.begruessung_ab_minuten, 0.0)

def lauf(es, urteil, von, bis):
    out = []
    for t in range(von, bis + 1):
        out += [(t, a) for a in es.schritt(urteil, float(t))]
    return out

def typen(aktionen): return [(t, type(a).__name__) for t, a in aktionen if not isinstance(a, IconStatus)]

def test_stufen_10_40_70():
    a = lauf(esk(), ABG(), 0, 75)
    assert typen(a) == [(10, "Hinweis"), (40, "OverlayZeigen"), (70, "Sperren")]
    assert (10, IconStatus("gelb")) in a and (40, IconStatus("rot")) in a
    assert (70, Sperren("domain:instagram.com")) in a

def test_ende_schliesst_overlay():
    es = esk(); lauf(es, ABG(), 0, 45)
    assert es.schritt(FOK, 46) == [OverlaySchliessen(), IconStatus("gruen")]

def test_rueckfall_eine_stufe_hoeher_und_vergessen():
    es = esk(); lauf(es, ABG(), 0, 15); lauf(es, FOK, 16, 60)
    assert typen(lauf(es, ABG(), 61, 101)) == [(71, "OverlayZeigen"), (101, "Sperren")]
    es2 = esk(); lauf(es2, ABG(), 0, 15); lauf(es2, FOK, 16, 400)
    assert typen(lauf(es2, ABG(), 401, 412)) == [(411, "Hinweis")]

def test_quellenwechsel_setzt_uhr_nicht_zurueck():
    es = esk(); lauf(es, ABG(), 0, 20)
    a = lauf(es, ABG("domain:tiktok.com"), 21, 45)
    assert (40, OverlayZeigen("Instagram", "domain:tiktok.com")) in a

def test_stufe3_sperrt_jede_neue_quelle():
    es = esk(); lauf(es, ABG(), 0, 72)
    assert (73, Sperren("domain:tiktok.com")) in lauf(es, ABG("domain:tiktok.com"), 73, 75)

def test_stichprobe_hoechstens_stufe_2_und_seit():
    es = esk()
    a = lauf(es, ABG("stichprobe", seit=0.0), 30, 100)
    assert typen(a) == [(30, "Hinweis"), (40, "OverlayZeigen")]

def test_handy_overlay_bis_5_s_ohne_handy():
    es = esk(); a = lauf(es, ABG("handy"), 0, 75)
    assert (70, HandyOverlay()) in a
    assert typen(lauf(es, FOK, 76, 79)) == []
    assert (80, OverlaySchliessen()) in lauf(es, FOK, 80, 80)

def test_zurueck_zur_aufgabe():
    es = esk(); lauf(es, ABG(), 0, 45)
    assert es.zurueck_zur_aufgabe(45) == [OverlaySchliessen()]
    assert typen(lauf(es, ABG(), 46, 50)) == [(50, "OverlayZeigen")]

def test_korrektur_ohne_rueckfall():
    es = esk(); lauf(es, ABG(), 0, 45)
    assert es.korrektur(45) == [OverlaySchliessen(), IconStatus("gruen")]
    lauf(es, FOK, 46, 59)
    assert typen(lauf(es, ABG(), 60, 70)) == [(70, "Hinweis")]

def test_abwesend_icon_und_begruessung():
    es = esk(); a = lauf(es, WEG, 0, 400)
    assert [x for _, x in a if isinstance(x, IconStatus)] == [IconStatus("blau")]
    assert Begruessung(6) in es.schritt(FOK, 401)
    es2 = esk(); lauf(es2, WEG, 0, 100)
    assert not any(isinstance(x, Begruessung) for x in es2.schritt(FOK, 101))
```

- [ ] **Step 2: Run tests to verify they fail** — `python -m pytest tests/test_escalation.py -v` → FAIL

- [ ] **Step 3: Implement `Eskalation`**

- [ ] **Step 4: Run tests to verify they pass** — `python -m pytest tests/test_escalation.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add FocusGuard/focusguard/escalation.py FocusGuard/tests/test_escalation.py
git commit -m "feat(focusguard): three-stage escalation with relapse and absence handling"
```

---

### Task 8: AI prompts and answer parsing

**Files:**
- Create: `FocusGuard/focusguard/ai/__init__.py`, `FocusGuard/focusguard/ai/prompts.py`
- Test: `FocusGuard/tests/test_prompts.py`

**Interfaces:**
- Consumes: `PcBeobachtung`, `KiUrteil`, `AufgabenListen`, `Status` (Task 1); `domain_aus_url` (Task 3)
- Produces:
  - `SYSTEM_URTEIL: str`, `SYSTEM_STARTLISTEN: str`, `URTEIL_SCHEMA: dict`, `STARTLISTEN_SCHEMA: dict`
  - `MISCH_PLATTFORMEN = frozenset({"youtube.com", "reddit.com", "x.com", "twitter.com", "google.com", "bing.com", "duckduckgo.com"})` plus every domain starting with `google.`
  - `class KiAntwortFehler(Exception)`
  - `bild_block(jpeg: bytes) -> dict` (base64 `image/jpeg`)
  - `startlisten_inhalt(aufgabe: str) -> list[dict]`, `seite_inhalt(aufgabe: str, pc: PcBeobachtung, bild: bytes | None) -> list[dict]`, `handy_inhalt(aufgabe: str, bild: bytes) -> list[dict]`, `stichprobe_inhalt(aufgabe: str, pc: PcBeobachtung | None, monitore: list[bytes], webcam: bytes | None) -> list[dict]` — image blocks first, then one text block
  - `baue_anfrage(modell: str, system: str, inhalt: list[dict], schema: dict) -> dict` → `{"model", "max_tokens": 2048, "system", "messages": [{"role": "user", "content": inhalt}], "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": schema}}}`
  - `parse_urteil(text: str, min_sicherheit: float) -> KiUrteil`, `parse_startlisten(text: str) -> AufgabenListen`

Schemas (`additionalProperties: false`, all properties required):
- `URTEIL_SCHEMA`: `status` enum `fokus|abgelenkt|unklar`, `begruendung` string, `sicherheit` number, `gilt_fuer` enum `seite|domain|programm`.
- `STARTLISTEN_SCHEMA`: arrays of strings `fokus_programme`, `fokus_domains`, `ablenkung_programme`, `ablenkung_domains`.

`SYSTEM_URTEIL` (exact copy):

```
Du bist der Fokus-Assistent einer Lern-App. Die Person hat sich eine Aufgabe vorgenommen und dich gebeten, ehrlich zu beurteilen, ob sie gerade daran arbeitet. Beurteile nur, was du auf den Bildern und in den Angaben siehst.
- fokus: Die Tätigkeit dient der Aufgabe, auch Recherche, Dokumentation, Tutorials, Notizen oder Hintergrundmusik.
- abgelenkt: Die Tätigkeit hat mit der Aufgabe nichts zu tun, etwa Social Media, Unterhaltung, Nachrichten, Shopping, Spiele oder Handy-Nutzung.
- unklar: Du kannst es nicht sicher sagen.
gilt_fuer: "domain" nur, wenn die ganze Website eindeutig zur Aufgabe passt oder eindeutig ablenkt. "programm" nur, wenn das ganze Programm eindeutig passt oder ablenkt. Sonst "seite".
sicherheit: Zahl von 0 bis 1.
begruendung: ein kurzer Satz auf Deutsch, direkt an die Person gerichtet (du).
```

`SYSTEM_STARTLISTEN` (exact copy):

```
Du hilfst einer Lern-App, Listen für eine Fokus-Session anzulegen. Nenne Windows-Programme (Prozessnamen wie blender.exe) und Domains (wie docs.blender.org), die eindeutig zur Aufgabe gehören, und solche, die bei dieser Aufgabe eindeutig ablenken. Gemischte Plattformen wie youtube.com, reddit.com, x.com oder google.com nimmst du in keine Liste auf. Höchstens 10 Einträge pro Liste.
```

User text blocks: `seite_inhalt` → `"Aufgabe: {aufgabe}\nProgramm: {prozess}\nFenstertitel: {titel}\nURL: {url or 'unbekannt'}\nPasst das gerade zur Aufgabe?"`; `handy_inhalt` → `"Aufgabe: {aufgabe}\nDas Webcam-Bild zeigt die Person am Schreibtisch, ein Handy wurde erkannt. Benutzt die Person das Handy gerade (abgelenkt), oder liegt es nur da bzw. dient es der Aufgabe (fokus)?"`; `stichprobe_inhalt` → `"Aufgabe: {aufgabe}\n"` + one line per image (`"Bild {n}: Monitor {m}"` / `"Bild {n}: Webcam"`) + active window lines when `pc` is given + `"Arbeitet die Person gerade an der Aufgabe?"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_prompts.py
import base64, json, pytest
from focusguard.ai.prompts import (parse_urteil, parse_startlisten, KiAntwortFehler, seite_inhalt,
                                   stichprobe_inhalt, baue_anfrage, SYSTEM_URTEIL, URTEIL_SCHEMA)
from focusguard.models import Status
from hilfen import pc

def j(**kw):
    d = {"status": "abgelenkt", "begruendung": "Instagram", "sicherheit": 0.9, "gilt_fuer": "domain"}; d.update(kw)
    return json.dumps(d)

def test_parse_urteil_gueltig_und_grenzen():
    u = parse_urteil(j(), 0.6)
    assert (u.status, u.begruendung, u.sicherheit, u.gilt_fuer) == (Status.ABGELENKT, "Instagram", 0.9, "domain")
    assert parse_urteil(j(sicherheit=0.5), 0.6).status is Status.UNKLAR
    assert parse_urteil(j(sicherheit=1.7), 0.6).sicherheit == 1.0

@pytest.mark.parametrize("text", ["", "kein json", "[]", '{"status": "fokus"}', j(status="weiss nicht"), j(gilt_fuer="alles")])
def test_parse_urteil_ungueltig_wirft(text):
    with pytest.raises(KiAntwortFehler):
        parse_urteil(text, 0.6)

def test_parse_startlisten_normalisiert_und_filtert():
    l = parse_startlisten(json.dumps({"fokus_programme": [" Blender.EXE "], "fokus_domains": ["WWW.Blender.org", "youtube.com", "google.de"],
                                      "ablenkung_programme": [], "ablenkung_domains": ["https://www.9gag.com/hot"]}))
    assert l.fokus_programme == ("blender.exe",) and l.fokus_domains == ("blender.org",) and l.ablenkung_domains == ("9gag.com",)

def test_seite_inhalt():
    inhalt = seite_inhalt("Blender lernen", pc(url="https://example.org/x", titel="T"), b"\xff\xd8jpg")
    assert inhalt[0]["type"] == "image" and base64.b64decode(inhalt[0]["source"]["data"]) == b"\xff\xd8jpg"
    assert all(s in inhalt[1]["text"] for s in ("Blender lernen", "chrome.exe", "T", "https://example.org/x"))
    assert [b["type"] for b in seite_inhalt("a", pc(), None)] == ["text"]

def test_stichprobe_inhalt():
    inhalt = stichprobe_inhalt("a", None, [b"m1", b"m2"], b"cam")
    assert [b["type"] for b in inhalt] == ["image", "image", "image", "text"]
    assert all(s in inhalt[-1]["text"] for s in ("Monitor 1", "Monitor 2", "Webcam"))

def test_baue_anfrage_ohne_sampling():
    k = baue_anfrage("claude-haiku-5-5", SYSTEM_URTEIL, [{"type": "text", "text": "x"}], URTEIL_SCHEMA)
    assert set(k) == {"model", "max_tokens", "system", "messages", "output_config"}
    assert k["model"] == "claude-haiku-5-5" and k["output_config"]["effort"] == "low"
    assert k["output_config"]["format"]["type"] == "json_schema"
```

- [ ] **Step 2: Run tests to verify they fail** — `python -m pytest tests/test_prompts.py -v` → FAIL

- [ ] **Step 3: Implement `prompts.py`** (`parse_startlisten` reuses `domain_aus_url` for domains, lowercases and strips programs, drops duplicates, keeps order)

- [ ] **Step 4: Run tests to verify they pass** — `python -m pytest tests/test_prompts.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add FocusGuard/focusguard/ai FocusGuard/tests/test_prompts.py
git commit -m "feat(focusguard): AI prompts, JSON schemas and answer parsing"
```

---

### Task 9: AI judge (rate limit, queue, sender)

**Files:**
- Create: `FocusGuard/focusguard/ai/client.py`
- Test: `FocusGuard/tests/test_ki_richter.py`

**Interfaces:**
- Consumes: Task 8 functions; `KiAnfrage`, `KiErgebnis`, `KiArt`, `AufgabenListen` (Task 1)
- Produces:
  - `class KiFehler(Exception)`; frozen dataclass `KiRohAntwort(text: str, tokens_ein: int, tokens_aus: int)`; `Sender = Callable[[dict], KiRohAntwort]`
  - `anthropic_sender(client=None, timeout_s: float = 15.0) -> Sender` — `client` defaults to `anthropic.Anthropic(timeout=timeout_s, max_retries=0)`; calls `client.messages.create(**kwargs)`; raises `KiFehler` for `stop_reason` `"refusal"` or `"max_tokens"`, for a response without a text block, and for any `anthropic.APIError`
  - `class BildquellePort(Protocol)`: `aktiver_monitor(fenster_id: int) -> bytes | None`, `alle_monitore() -> list[bytes]`, `webcam() -> bytes | None`
  - `class Ratenbegrenzer(pro_minute: int, uhr: Uhr)` with `versuche() -> bool` (token bucket, capacity `pro_minute`, refill `pro_minute` per 60 s)
  - `class KiRichter(sender: Sender, bilder: BildquellePort, modell: str, min_sicherheit: float, pro_minute: int, uhr: Uhr, ablage: Path | None = None)` with `einreihen(anfrage: KiAnfrage, aufgabe: str) -> None` (ignored if the same quelle is queued), `verarbeite_naechste() -> KiErgebnis | None` (thread-safe; `None` when the queue is empty or the rate limit says no; lowest `prioritaet` first, then oldest; images captured at send time), `startlisten(aufgabe: str) -> AufgabenListen | None` (not rate limited; `None` on any error), `leeren() -> None`

Behaviour of `verarbeite_naechste`: SEITE → `aktiver_monitor(pc.fenster_id)` (exception → no image); HANDY → `webcam()`, `None` → `KiErgebnis(anfrage, None, "Kein Webcam-Bild")` without calling the sender; STICHPROBE → `alle_monitore()` if `mit_bildschirm`, `webcam()` if `mit_webcam`. `KiFehler`/`KiAntwortFehler` → `KiErgebnis(anfrage, None, str(fehler), tokens…)`. With `ablage`, write every sent image as `<ms>_<art>_<n>.jpg` and `<ms>_<art>.json` (`{"quelle", "urteil" | "fehler"}`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ki_richter.py
import json, types, pytest
from focusguard.ai.client import KiRichter, Ratenbegrenzer, KiRohAntwort, KiFehler, anthropic_sender
from focusguard.clock import TestUhr
from focusguard.models import KiAnfrage, KiArt, Status
from hilfen import pc

ANTWORT = json.dumps({"status": "fokus", "begruendung": "passt", "sicherheit": 0.9, "gilt_fuer": "seite"})

class FakeSender:
    def __init__(self, text=ANTWORT, fehler=None): self.aufrufe, self.text, self.fehler = [], text, fehler
    def __call__(self, kwargs):
        self.aufrufe.append(kwargs)
        if self.fehler: raise self.fehler
        return KiRohAntwort(self.text, 1200, 40)

class FakeBilder:
    def __init__(self, cam=b"cam", monitor_fehler=False): self.cam, self.mf = cam, monitor_fehler
    def aktiver_monitor(self, fid):
        if self.mf: raise OSError("kein Monitor")
        return b"mon"
    def alle_monitore(self): return [b"m1", b"m2"]
    def webcam(self): return self.cam

def anfrage(art=KiArt.SEITE, quelle="seite:a|b", **kw):
    return KiAnfrage(art, quelle, 0.0, kw.get("pc", pc(url="https://a.org", titel="b")), kw.get("bs", True), kw.get("wc", False))

def richter(sender=None, bilder=None, uhr=None, ablage=None):
    return KiRichter(sender or FakeSender(), bilder or FakeBilder(), "claude-haiku-5-5", 0.6, 2, uhr or TestUhr(0), ablage)

def bilder_typen(kwargs): return [b["type"] for b in kwargs["messages"][0]["content"]]

def test_ratenbegrenzer():
    u = TestUhr(0); r = Ratenbegrenzer(2, u)
    assert r.versuche() and r.versuche() and not r.versuche()
    u.vor(30); assert r.versuche() and not r.versuche()

def test_reihenfolge_und_duplikate():
    s = FakeSender(); r = richter(s)
    assert r.verarbeite_naechste() is None
    r.einreihen(anfrage(KiArt.STICHPROBE, "stichprobe"), "a"); r.einreihen(anfrage(), "a"); r.einreihen(anfrage(), "a")
    r.einreihen(anfrage(KiArt.HANDY, "handy", bs=False, wc=True), "a")
    arten = [r.verarbeite_naechste().anfrage.art for _ in range(2)]
    assert arten == [KiArt.HANDY, KiArt.SEITE] and r.verarbeite_naechste() is None   # rate limit
    assert len(s.aufrufe) == 2

def test_ergebnis_mit_tokens_und_bild():
    s = FakeSender(); r = richter(s); r.einreihen(anfrage(), "Blender")
    e = r.verarbeite_naechste()
    assert e.urteil.status is Status.FOKUS and (e.tokens_ein, e.tokens_aus) == (1200, 40) and e.fehler is None
    assert bilder_typen(s.aufrufe[0]) == ["image", "text"]

def test_fehler_ergeben_ergebnis_ohne_urteil():
    r = richter(FakeSender(fehler=KiFehler("Netz weg"))); r.einreihen(anfrage(), "a")
    e = r.verarbeite_naechste(); assert e.urteil is None and "Netz weg" in e.fehler
    r = richter(FakeSender(text="kaputt")); r.einreihen(anfrage(), "a")
    assert r.verarbeite_naechste().urteil is None

def test_handy_ohne_webcam_bild_ohne_aufruf():
    s = FakeSender(); r = richter(s, FakeBilder(cam=None)); r.einreihen(anfrage(KiArt.HANDY, "handy", bs=False, wc=True), "a")
    assert r.verarbeite_naechste().fehler == "Kein Webcam-Bild" and s.aufrufe == []

def test_monitorfehler_seite_nur_text():
    s = FakeSender(); r = richter(s, FakeBilder(monitor_fehler=True)); r.einreihen(anfrage(), "a")
    r.verarbeite_naechste(); assert bilder_typen(s.aufrufe[0]) == ["text"]

def test_stichprobe_bilder():
    s = FakeSender(); r = richter(s); r.einreihen(anfrage(KiArt.STICHPROBE, "stichprobe", wc=True), "a")
    r.verarbeite_naechste(); assert bilder_typen(s.aufrufe[0]) == ["image", "image", "image", "text"]

def test_ablage(tmp_path):
    r = richter(ablage=tmp_path); r.einreihen(anfrage(), "a"); r.verarbeite_naechste()
    assert len(list(tmp_path.glob("*.jpg"))) == 1 and len(list(tmp_path.glob("*.json"))) == 1

def test_startlisten_und_leeren():
    text = json.dumps({"fokus_programme": ["blender.exe"], "fokus_domains": [], "ablenkung_programme": [], "ablenkung_domains": []})
    r = richter(FakeSender(text=text))
    for _ in range(5): assert r.startlisten("Blender").fokus_programme == ("blender.exe",)
    assert richter(FakeSender(fehler=KiFehler("x"))).startlisten("a") is None
    r2 = richter(); r2.einreihen(anfrage(), "a"); r2.leeren(); assert r2.verarbeite_naechste() is None

def test_anthropic_sender_refusal_und_max_tokens():
    def client(stop, bloecke):
        antwort = types.SimpleNamespace(stop_reason=stop, content=bloecke, usage=types.SimpleNamespace(input_tokens=5, output_tokens=2))
        return types.SimpleNamespace(messages=types.SimpleNamespace(create=lambda **kw: antwort))
    text = [types.SimpleNamespace(type="text", text=ANTWORT)]
    assert anthropic_sender(client("end_turn", text))({}).text == ANTWORT
    for stop, bloecke in (("refusal", text), ("max_tokens", text), ("end_turn", [])):
        with pytest.raises(KiFehler):
            anthropic_sender(client(stop, bloecke))({})
```

- [ ] **Step 2: Run tests to verify they fail** — `python -m pytest tests/test_ki_richter.py -v` → FAIL

- [ ] **Step 3: Implement `client.py`** (`threading.Lock` around queue and limiter; `import anthropic` inside `anthropic_sender`)

- [ ] **Step 4: Run tests to verify they pass** — `python -m pytest tests/test_ki_richter.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add FocusGuard/focusguard/ai/client.py FocusGuard/tests/test_ki_richter.py
git commit -m "feat(focusguard): AI judge with priority queue, rate limit and Anthropic sender"
```

---

### Task 10: Screen capture and JPEG encoding

**Files:**
- Create: `FocusGuard/focusguard/capture.py`
- Test: `FocusGuard/tests/test_capture.py`

**Interfaces:**
- Consumes: `BildquellePort` (Task 9)
- Produces:
  - `verkleinere_jpeg(bild: np.ndarray, lange_kante: int, qualitaet: int = 80) -> bytes` — accepts BGR or BGRA; shrinks with `cv2.INTER_AREA` so the long edge equals `lange_kante`; never enlarges
  - `class Bildschirm(kamera_jpeg: Callable[[], bytes | None])` implementing `BildquellePort` (called from the AI worker thread: create a fresh `mss.mss()` inside each call): `alle_monitore()` (every `mss` monitor except index 0, 1280 px), `aktiver_monitor(fenster_id)` (Windows: `win32api.MonitorFromWindow(fenster_id, MONITOR_DEFAULTTONEAREST)` → `GetMonitorInfo(...)["Monitor"]` rectangle grabbed with `mss`; other platforms or errors: primary monitor), `webcam()` → `kamera_jpeg()`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_capture.py
import cv2, numpy as np
from focusguard.capture import verkleinere_jpeg

def dekodiere(data): return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)

def test_lange_kante():
    data = verkleinere_jpeg(np.zeros((1440, 2560, 3), np.uint8), 1280)
    assert data[:2] == b"\xff\xd8" and dekodiere(data).shape[:2] == (720, 1280)

def test_hochformat_und_kein_vergroessern():
    assert dekodiere(verkleinere_jpeg(np.zeros((2000, 1000, 3), np.uint8), 1280)).shape[:2] == (1280, 640)
    assert dekodiere(verkleinere_jpeg(np.zeros((480, 640, 3), np.uint8), 1280)).shape[:2] == (480, 640)

def test_bgra():
    assert dekodiere(verkleinere_jpeg(np.zeros((100, 200, 4), np.uint8), 1280)).shape == (100, 200, 3)
```

- [ ] **Step 2: Run tests to verify they fail** — `python -m pytest tests/test_capture.py -v` → FAIL

- [ ] **Step 3: Implement `capture.py`** (`mss` and `win32api` imported inside methods)

- [ ] **Step 4: Run tests to verify they pass** — `python -m pytest tests/test_capture.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add FocusGuard/focusguard/capture.py FocusGuard/tests/test_capture.py
git commit -m "feat(focusguard): screenshot capture and JPEG downscaling"
```

---

### Task 11: Sensor thread and PC sensor

**Files:**
- Create: `FocusGuard/focusguard/sensors/__init__.py`, `FocusGuard/focusguard/sensors/base.py`, `FocusGuard/focusguard/sensors/pc.py`
- Test: `FocusGuard/tests/test_sensor_base.py`, `FocusGuard/tests/test_pc_sensor.py`

**Interfaces:**
- Consumes: `PcBeobachtung` (Task 1), `domain_aus_url`, `BROWSER_PROZESSE` (Task 3)
- Produces (`base.py`):
  - `class AbsturzZaehler(max_abstuerze: int = 3, fenster_s: float = 300.0)` with `absturz(jetzt: float) -> bool` (`False` = give up)
  - `class SensorThread(threading.Thread)(name: str, schritt: Callable[[], list], intervall_s: float, ausgabe: Callable[[object], None], fehler: Callable[[str, str], None], uhr: Uhr = time.time, neustart_s: float = 5.0, beim_stopp: Callable[[], None] | None = None)`, daemon; `stoppe() -> None`. Loop: call `schritt`, pass each item to `ausgabe`, wait `intervall_s` on a stop event. Exception → `fehler(name, repr(exc))`, then `AbsturzZaehler`; give up → `fehler(name, "Sensor dauerhaft ausgeschaltet")` and end; else wait `neustart_s`. `beim_stopp` runs when the loop ends.
- Produces (`pc.py`):
  - `URL_LESBAR = frozenset({"chrome.exe", "msedge.exe", "brave.exe"})`
  - `beobachtung_aus(zeit: float, fenster_id: int, prozess: str, titel: str, url: str | None) -> PcBeobachtung` (prozess lowercased)
  - `class PcSensor(lies_vordergrund: Callable[[], tuple[int, int, str, str] | None], lies_url: Callable[[int, str], str | None], uhr: Uhr, eigene_pid: int)` with `schritt() -> list[PcBeobachtung]`; `lies_vordergrund` returns `(fenster_id, pid, prozess, titel)`; returns `[]` for no window or `pid == eigene_pid`; calls `lies_url` only for `URL_LESBAR` processes and only when `(fenster_id, titel)` changed (cached otherwise)
  - `windows_vordergrund() -> tuple[int, int, str, str] | None` (`win32gui.GetForegroundWindow`, `win32process.GetWindowThreadProcessId`, `psutil.Process(pid).name()`, `win32gui.GetWindowText`)
  - `windows_url(fenster_id: int, prozess: str) -> str | None` (`uiautomation`: `SetGlobalSearchTimeout(0.5)`, `ControlFromHandle(fenster_id).EditControl(searchDepth=12)`, `GetValuePattern().Value`; any exception → `None`)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sensor_base.py
import threading, time
from focusguard.sensors.base import AbsturzZaehler, SensorThread

def test_absturzzaehler():
    z = AbsturzZaehler(3, 300)
    assert z.absturz(0) and z.absturz(10) and not z.absturz(20)
    z2 = AbsturzZaehler(3, 300)
    assert z2.absturz(0) and z2.absturz(100) and z2.absturz(400)

def warte(bedingung, s=2.0):
    ende = time.time() + s
    while time.time() < ende and not bedingung(): time.sleep(0.01)
    return bedingung()

def test_liefert_und_stoppt():
    raus, gestoppt = [], threading.Event()
    t = SensorThread("pc", lambda: ["x"], 0.01, raus.append, lambda *a: None, beim_stopp=gestoppt.set)
    t.start(); assert warte(lambda: len(raus) >= 3)
    t.stoppe(); t.join(1); assert not t.is_alive() and gestoppt.is_set()

def test_neustart_und_aufgeben():
    zaehler, raus, fehler = {"n": 0}, [], []
    def schritt():
        zaehler["n"] += 1
        if zaehler["n"] == 1: raise RuntimeError("kaputt")
        return ["ok"]
    t = SensorThread("pc", schritt, 0.01, raus.append, lambda n, m: fehler.append(m), neustart_s=0.01)
    t.start(); assert warte(lambda: raus); t.stoppe(); t.join(1)
    assert len(fehler) == 1 and "kaputt" in fehler[0]
    fehler2 = []
    def immer(): raise RuntimeError("immer")
    t2 = SensorThread("cam", immer, 0.01, raus.append, lambda n, m: fehler2.append(m), neustart_s=0.01)
    t2.start(); t2.join(2)
    assert not t2.is_alive() and fehler2[-1] == "Sensor dauerhaft ausgeschaltet"
```

```python
# tests/test_pc_sensor.py
import os
from focusguard.sensors.pc import beobachtung_aus, PcSensor

def test_beobachtung_aus():
    b = beobachtung_aus(5.0, 42, "Chrome.EXE", "YouTube", "youtube.com/watch")
    assert (b.prozess, b.domain, b.ist_browser, b.fenster_id) == ("chrome.exe", "youtube.com", True, 42)

def test_pc_sensor_ignoriert_eigenes_fenster():
    s = PcSensor(lambda: (1, os.getpid(), "python.exe", "FocusGuard"), lambda f, p: None, lambda: 1.0, os.getpid())
    assert s.schritt() == []

def test_kein_fenster():
    assert PcSensor(lambda: None, lambda f, p: None, lambda: 1.0, 1).schritt() == []

def test_url_nur_bei_titelwechsel_und_nur_lesbare_browser():
    aufrufe, fenster = [], {"v": (7, 99, "chrome.exe", "A")}
    s = PcSensor(lambda: fenster["v"], lambda f, p: aufrufe.append(f) or "https://a.org", lambda: 1.0, 1)
    assert s.schritt()[0].domain == "a.org"; s.schritt()
    assert len(aufrufe) == 1
    fenster["v"] = (7, 99, "chrome.exe", "B"); s.schritt(); assert len(aufrufe) == 2
    fenster["v"] = (8, 98, "firefox.exe", "C")
    [b] = s.schritt(); assert b.url is None and len(aufrufe) == 2
```

- [ ] **Step 2: Run tests to verify they fail** — `python -m pytest tests/test_sensor_base.py tests/test_pc_sensor.py -v` → FAIL

- [ ] **Step 3: Implement `base.py` and `pc.py`** (Windows imports inside `windows_vordergrund` / `windows_url`)

- [ ] **Step 4: Run tests to verify they pass** — same command → PASS

- [ ] **Step 5: Commit**

```bash
git add FocusGuard/focusguard/sensors FocusGuard/tests/test_sensor_base.py FocusGuard/tests/test_pc_sensor.py
git commit -m "feat(focusguard): restartable sensor thread and PC foreground sensor"
```

---

### Task 12: Camera sensors and sensor management

**Files:**
- Create: `FocusGuard/focusguard/sensors/modelle.py`, `FocusGuard/focusguard/sensors/gesicht.py`, `FocusGuard/focusguard/sensors/handy.py`, `FocusGuard/focusguard/sensors/kamera.py`, `FocusGuard/focusguard/sensors/verwaltung.py`
- Test: `FocusGuard/tests/test_kamera_sensoren.py`, `FocusGuard/tests/test_verwaltung.py`

**Interfaces:**
- Consumes: `SensorThread` (Task 11), `PcSensor`, `windows_vordergrund`, `windows_url` (Task 11), `verkleinere_jpeg` (Task 10), `WebcamBeobachtung`, `HandyBeobachtung` (Task 1)
- Produces:
  - `modelle.py`: `GESICHT_MODELL = ("face_landmarker.task", "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task")`, `OBJEKT_MODELL = ("efficientdet_lite0.tflite", "https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/float16/1/efficientdet_lite0.tflite")`, `class ModellFehler(Exception)`, `stelle_modell_bereit(dateiname: str, url: str, ordner: Path, herunterladen: Callable[[str, Path], None] | None = None) -> Path` (downloads once to `<ordner>/<dateiname>` via a `.part` file then rename; any exception → `ModellFehler`)
  - `gesicht.py`: `pitch_aus_matrix(m: np.ndarray) -> float` = `degrees(atan2(R[2,1], R[2,2]))` of the upper-left 3×3 (positive = head down, MediaPipe y-up camera space); `class GesichtsAnalyse(modell_pfad: Path)` with `analysiere(bild_bgr: np.ndarray) -> tuple[bool, float | None]` (FaceLandmarker, IMAGE mode, `num_faces=1`, `output_facial_transformation_matrixes=True`)
  - `handy.py`: `HANDY_KATEGORIE = "cell phone"`, `HANDY_SCHWELLE = 0.5`, `handy_score(erkennungen: Iterable[tuple[str, float]]) -> float` (max score of that category, else 0.0); `class HandyErkennung(modell_pfad: Path)` with `analysiere(bild_bgr) -> float` (ObjectDetector, `score_threshold=0.3`, `category_allowlist=["cell phone"]`)
  - `kamera.py`: `class Kamera(index: int = 0, oeffnen: Callable[[int], object] | None = None)` (default opener `cv2.VideoCapture(index, cv2.CAP_DSHOW)` on Windows) with `oeffne() -> bool`, `lies() -> np.ndarray | None`, `letztes_jpeg() -> bytes | None` (thread-safe, 640 px), `schliesse()`; `class KameraSensor(kamera, gesicht: GesichtsAnalyse-like, handy: HandyErkennung-like | None, uhr)` with `schritt() -> list[WebcamBeobachtung | HandyBeobachtung]`, property `problem -> str | None`, `letztes_jpeg() -> bytes | None` (delegates to the camera), `schliesse()`. Not open → try `oeffne()` at most every 30 s (first try immediately), `problem = "Kamera nicht verfügbar"`; `lies()` returns `None` → close, set problem, retry after 30 s.
  - `verwaltung.py`: `class SensorVerwaltung(ausgabe, fehler, pc_fabrik: Callable[[], Callable[[], list]], kamera_fabrik: Callable[[bool], KameraSensor-like], thread_fabrik=SensorThread)` with `setze(pc: bool, webcam: bool, smartphone: bool) -> None` (PC thread `"pc"` at 1.0 s; camera thread `"kamera"` at 0.5 s running while webcam or smartphone is on; restarted when the smartphone flag changes; threads are created as `thread_fabrik(name, schritt, intervall_s, ausgabe, fehler, beim_stopp=…)` with `beim_stopp=kamera_sensor.schliesse` for the camera), `stoppe() -> None`, `problem() -> str | None` (the camera sensor's problem), `kamera_jpeg() -> bytes | None` (the running camera sensor's `letztes_jpeg()`, else `None`); `standard_verwaltung(ausgabe, fehler, datenordner: Path) -> SensorVerwaltung` wires `PcSensor(windows_vordergrund, windows_url, time.time, os.getpid())` and `KameraSensor(Kamera(), GesichtsAnalyse(...), HandyErkennung(...) if smartphone else None, time.time)` with models from `stelle_modell_bereit(..., datenordner / "modelle")`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_kamera_sensoren.py
import math, numpy as np, pytest
from focusguard.sensors.gesicht import pitch_aus_matrix
from focusguard.sensors.handy import handy_score
from focusguard.sensors.kamera import KameraSensor
from focusguard.sensors.modelle import stelle_modell_bereit, ModellFehler
from focusguard.models import WebcamBeobachtung, HandyBeobachtung
from focusguard.clock import TestUhr

def rx(grad):
    c, s = math.cos(math.radians(grad)), math.sin(math.radians(grad))
    m = np.eye(4); m[1:3, 1:3] = [[c, -s], [s, c]]; return m

def test_pitch():
    assert pitch_aus_matrix(np.eye(4)) == pytest.approx(0)
    assert pitch_aus_matrix(rx(25)) == pytest.approx(25) and pitch_aus_matrix(rx(-10)) == pytest.approx(-10)

def test_handy_score():
    assert handy_score([("cell phone", 0.7), ("person", 0.9), ("cell phone", 0.4)]) == 0.7
    assert handy_score([]) == 0.0

class FakeKamera:
    def __init__(self, auf=True): self.auf, self.versuche, self.offen = auf, 0, False
    def oeffne(self): self.versuche += 1; self.offen = self.auf; return self.auf
    def lies(self): return np.zeros((480, 640, 3), np.uint8) if self.offen else None
    def schliesse(self): self.offen = False

class Fix:
    def __init__(self, wert): self.wert = wert
    def analysiere(self, bild): return self.wert

def test_kamera_sensor_liefert():
    u = TestUhr(5)
    s = KameraSensor(FakeKamera(), Fix((True, 12.0)), Fix(0.8), u)
    assert s.schritt() == [WebcamBeobachtung(5, True, 12.0), HandyBeobachtung(5, True, 0.8)]
    s2 = KameraSensor(FakeKamera(), Fix((False, None)), Fix(0.3), u)
    assert s2.schritt()[1] == HandyBeobachtung(5, False, 0.3)
    assert KameraSensor(FakeKamera(), Fix((True, 1.0)), None, u).schritt() == [WebcamBeobachtung(5, True, 1.0)]

def test_kamera_nicht_verfuegbar_neuer_versuch_nach_30_s():
    u, k = TestUhr(0), FakeKamera(auf=False)
    s = KameraSensor(k, Fix((True, 0.0)), None, u)
    assert s.schritt() == [] and s.problem == "Kamera nicht verfügbar" and k.versuche == 1
    u.vor(10); s.schritt(); assert k.versuche == 1
    u.vor(21); k.auf = True; assert len(s.schritt()) == 1 and s.problem is None

def test_modell_einmal_laden(tmp_path):
    aufrufe = []
    def lade(url, ziel): aufrufe.append(url); ziel.write_bytes(b"modell")
    p = stelle_modell_bereit("m.task", "https://x/m.task", tmp_path, lade)
    stelle_modell_bereit("m.task", "https://x/m.task", tmp_path, lade)
    assert p.read_bytes() == b"modell" and len(aufrufe) == 1
    def kaputt(url, ziel): raise OSError("offline")
    with pytest.raises(ModellFehler):
        stelle_modell_bereit("n.task", "https://x/n.task", tmp_path, kaputt)
```

```python
# tests/test_verwaltung.py
from focusguard.sensors.verwaltung import SensorVerwaltung

class FakeThread:
    alle = []
    def __init__(self, name, schritt, intervall_s, ausgabe, fehler, beim_stopp=None, **kw):
        self.name, self.laeuft, self.beim_stopp = name, False, beim_stopp; FakeThread.alle.append(self)
    def start(self): self.laeuft = True
    def stoppe(self): self.laeuft = False
    def join(self, timeout=None): pass

class FakeKameraSensor:
    def __init__(self, smartphone): self.smartphone, self.problem = smartphone, None
    def schritt(self): return []
    def schliesse(self): pass

def test_setze_und_stoppe():
    FakeThread.alle = []; kameras = []
    v = SensorVerwaltung(print, print, lambda: (lambda: []), lambda sp: kameras.append(FakeKameraSensor(sp)) or kameras[-1], FakeThread)
    v.setze(True, False, False)
    assert [(t.name, t.laeuft) for t in FakeThread.alle] == [("pc", True)]
    v.setze(True, True, False); assert kameras[-1].smartphone is False
    v.setze(True, True, True)
    assert kameras[-1].smartphone is True and len(kameras) == 2
    assert [t.laeuft for t in FakeThread.alle if t.name == "kamera"] == [False, True]
    v.setze(False, False, False); assert not any(t.laeuft for t in FakeThread.alle)
    v.setze(True, True, True); v.stoppe(); assert not any(t.laeuft for t in FakeThread.alle)
```

- [ ] **Step 2: Run tests to verify they fail** — `python -m pytest tests/test_kamera_sensoren.py tests/test_verwaltung.py -v` → FAIL

- [ ] **Step 3: Implement the five modules** (`mediapipe` imported inside `GesichtsAnalyse`/`HandyErkennung` constructors; frames converted BGR→RGB and wrapped in `mediapipe.Image(image_format=mediapipe.ImageFormat.SRGB, data=…)`; `urllib.request.urlretrieve` as the default downloader)

- [ ] **Step 4: Run tests to verify they pass** — same command → PASS

- [ ] **Step 5: Commit**

```bash
git add FocusGuard/focusguard/sensors FocusGuard/tests/test_kamera_sensoren.py FocusGuard/tests/test_verwaltung.py
git commit -m "feat(focusguard): webcam face/phone sensors and sensor management"
```

---

### Task 13: Blocker

**Files:**
- Create: `FocusGuard/focusguard/blocker.py`
- Test: `FocusGuard/tests/test_blocker.py`

**Interfaces:**
- Consumes: `PcBeobachtung`, `AufgabenListen` (Task 1); `domain_passt`, `programm_passt` (Task 3); `seiten_schluessel` (Task 4)
- Produces:
  - `sperr_aktion(b: PcBeobachtung, gesperrt: Iterable[str], nie_sperren: Iterable[str], fokus: AufgabenListen) -> str | None` → `"tab_schliessen"`, `"minimieren"` or `None`. `None` if `b.prozess` is in `nie_sperren` or on `fokus.fokus_programme`, or `b.domain` matches `fokus.fokus_domains`. `domain:x` matching `b.domain` in a browser → `"tab_schliessen"`; `seite:k` with `seiten_schluessel(b) == k` → `"tab_schliessen"` in a browser, else `"minimieren"`; `prozess:p` equal to `b.prozess` → `"minimieren"`.
  - `class Blocker(nie_sperren: Iterable[str], uhr: Uhr, minimiere: Callable[[int], None], strg_w: Callable[[], None], vordergrund: Callable[[], int])` with `pruefe(b, gesperrt, fokus) -> str | None` — executes the action at most once per 2 s; skips (returns `None`) when `vordergrund() != b.fenster_id`; an exception from `minimiere`/`strg_w` is caught and returns `"fehler"` (the overlay stays as fallback)
  - `windows_blocker(nie_sperren, uhr) -> Blocker` (`win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)`; Ctrl+W via `win32api.keybd_event` down/up for `VK_CONTROL` and `ord("W")`; `win32gui.GetForegroundWindow`)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_blocker.py
from focusguard.blocker import sperr_aktion, Blocker
from focusguard.models import AufgabenListen
from focusguard.clock import TestUhr
from hilfen import pc

NIE = ("explorer.exe", "taskmgr.exe")

def test_sperr_aktionen():
    leer = AufgabenListen()
    assert sperr_aktion(pc(url="https://m.instagram.com/x"), {"domain:instagram.com"}, NIE, leer) == "tab_schliessen"
    assert sperr_aktion(pc("steam.exe"), {"prozess:steam.exe"}, NIE, leer) == "minimieren"
    assert sperr_aktion(pc(url="https://youtube.com/w", titel="Katzen"), {"seite:youtube.com|Katzen"}, NIE, leer) == "tab_schliessen"
    assert sperr_aktion(pc("game.exe", titel="Level 1"), {"seite:game.exe|Level 1"}, NIE, leer) == "minimieren"
    assert sperr_aktion(pc(url="https://example.org"), {"domain:instagram.com"}, NIE, leer) is None

def test_nie_sperren_und_fokus_vorrang():
    assert sperr_aktion(pc("explorer.exe"), {"prozess:explorer.exe"}, NIE, AufgabenListen()) is None
    assert sperr_aktion(pc(url="https://instagram.com"), {"domain:instagram.com"}, NIE, AufgabenListen(fokus_domains=("instagram.com",))) is None

def blocker(uhr, vorne=1):
    log = []
    return Blocker(NIE, uhr, lambda h: log.append(("min", h)), lambda: log.append(("w",)), lambda: vorne), log

def test_blocker_cooldown_2_s():
    u = TestUhr(0); b, log = blocker(u)
    insta = pc(url="https://instagram.com", fenster_id=1)
    assert b.pruefe(insta, {"domain:instagram.com"}, AufgabenListen()) == "tab_schliessen"
    u.vor(1); assert b.pruefe(insta, {"domain:instagram.com"}, AufgabenListen()) is None
    u.vor(1.1); b.pruefe(insta, {"domain:instagram.com"}, AufgabenListen())
    assert log == [("w",), ("w",)]

def test_blocker_tab_nur_wenn_fenster_noch_vorne():
    b, log = blocker(TestUhr(0), vorne=2)
    assert b.pruefe(pc(url="https://instagram.com", fenster_id=1), {"domain:instagram.com"}, AufgabenListen()) is None
    assert log == []

def test_blocker_minimiert_fenster_und_faengt_fehler():
    b, log = blocker(TestUhr(0), vorne=5)
    b.pruefe(pc("steam.exe", fenster_id=5), {"prozess:steam.exe"}, AufgabenListen())
    assert log == [("min", 5)]
    def kaputt(h): raise OSError("Zugriff verweigert")
    b2 = Blocker(NIE, TestUhr(0), kaputt, lambda: None, lambda: 5)
    assert b2.pruefe(pc("steam.exe", fenster_id=5), {"prozess:steam.exe"}, AufgabenListen()) == "fehler"
```

- [ ] **Step 2: Run tests to verify they fail** — `python -m pytest tests/test_blocker.py -v` → FAIL

- [ ] **Step 3: Implement `blocker.py`**

- [ ] **Step 4: Run tests to verify they pass** — `python -m pytest tests/test_blocker.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add FocusGuard/focusguard/blocker.py FocusGuard/tests/test_blocker.py
git commit -m "feat(focusguard): blocker that minimizes programs and closes tabs"
```

---

### Task 14: Session report

**Files:**
- Create: `FocusGuard/focusguard/auswertung.py`
- Test: `FocusGuard/tests/test_auswertung.py`

**Interfaces:**
- Consumes: `Session`, `Ereignis`, `Status` (Task 1)
- Produces:
  - `PREISE: dict[str, tuple[float, float]] = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00), "claude-opus-5-5": (4.00, 20.00)}` (USD per million input/output tokens)
  - frozen dataclass `Auswertung(session_id: int, aufgabe: str, start: float, dauer_min: int, geplant_min: int, vorzeitig: bool, sekunden: dict[Status, float], fokusquote: float | None, top_ablenkungen: list[tuple[str, int, float]], eskalationen: dict[int, int], sperren: int, aufhebungen: int, korrekturen: int, ki_aufrufe: int, kosten_usd: float | None)`
  - `berechne(session: Session, ereignisse: list[Ereignis], modell: str, jetzt: float) -> Auswertung`

Rules: events may arrive in any order — sort by `zeit` first. Every `statuswechsel` event starts a segment with its `status` and `quelle`, lasting until the next one or `session.ende` (or `jetzt` while running). `fokusquote = FOKUS / (gesamt − ABWESEND)`, `None` if the denominator is 0. Top 5 distractions by total seconds over ABGELENKT segments grouped by quelle (anzahl = segments). `eskalationen` counts `details["stufe"]` of `eskalation` events. `sperren`/`aufhebungen`/`korrekturen` count events `sperre`, `sperre_aufgehoben`, `korrektur`. KI costs from `details["tokens_ein"]`/`["tokens_aus"]` of `ki_aufruf` events; unknown model → `None`. `dauer_min = round((ende − start) / 60)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_auswertung.py
import pytest
from focusguard.auswertung import berechne
from focusguard.models import Session, Ereignis, Status

def ev(t, art, quelle="", status="", **details): return Ereignis(t, art, quelle, status, details)

SESSION = Session(1, "Blender", "blender", 0.0, 50, ende=600.0, vorzeitig_beendet=True)
EREIGNISSE = [
    ev(0, "statuswechsel", "", "fokus"), ev(100, "statuswechsel", "domain:instagram.com", "abgelenkt"),
    ev(110, "eskalation", "domain:instagram.com", "abgelenkt", stufe=1), ev(160, "statuswechsel", "", "fokus"),
    ev(200, "statuswechsel", "handy", "abgelenkt"), ev(210, "statuswechsel", "", "fokus"),
    ev(400, "statuswechsel", "", "abwesend"), ev(500, "statuswechsel", "", "fokus"),
    ev(50, "ki_aufruf", "seite:a|b", "fokus", tokens_ein=900_000, tokens_aus=50_000),
    ev(60, "ki_aufruf", "stichprobe", "", tokens_ein=100_000, tokens_aus=50_000),
    ev(170, "sperre", "domain:instagram.com"), ev(180, "sperre_aufgehoben"), ev(190, "korrektur", "handy")]

def test_zeiten_und_fokusquote():
    a = berechne(SESSION, EREIGNISSE, "claude-haiku-5-5", 999)
    assert a.sekunden[Status.FOKUS] == 430 and a.sekunden[Status.ABGELENKT] == 70 and a.sekunden[Status.ABWESEND] == 100
    assert a.fokusquote == pytest.approx(430 / 500)
    assert (a.dauer_min, a.geplant_min, a.vorzeitig) == (10, 50, True)

def test_top_und_zaehler():
    a = berechne(SESSION, EREIGNISSE, "claude-haiku-5-5", 999)
    assert a.top_ablenkungen == [("domain:instagram.com", 1, 60.0), ("handy", 1, 10.0)]
    assert a.eskalationen == {1: 1} and (a.sperren, a.aufhebungen, a.korrekturen, a.ki_aufrufe) == (1, 1, 1, 2)
    assert a.kosten_usd == pytest.approx(0.15)

def test_unbekanntes_modell_und_laufende_session():
    assert berechne(SESSION, EREIGNISSE, "anderes", 999).kosten_usd is None
    laufend = Session(2, "a", "a", 0.0, 25)
    a = berechne(laufend, [ev(0, "statuswechsel", "", "fokus")], "claude-haiku-5-5", 120.0)
    assert a.sekunden[Status.FOKUS] == 120 and a.fokusquote == 1.0

def test_nur_abwesend_ohne_quote():
    s = Session(3, "a", "a", 0.0, 25, ende=60.0)
    assert berechne(s, [ev(0, "statuswechsel", "", "abwesend")], "claude-haiku-5-5", 60).fokusquote is None
```

- [ ] **Step 2: Run tests to verify they fail** — `python -m pytest tests/test_auswertung.py -v` → FAIL

- [ ] **Step 3: Implement `auswertung.py`** (only `statuswechsel` events define segments; other event types are ignored for timing)

- [ ] **Step 4: Run tests to verify they pass** — `python -m pytest tests/test_auswertung.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add FocusGuard/focusguard/auswertung.py FocusGuard/tests/test_auswertung.py
git commit -m "feat(focusguard): session report with focus ratio, top distractions and AI cost"
```

---

### Task 15: Steuerung (orchestrator)

**Files:**
- Create: `FocusGuard/focusguard/steuerung.py`
- Test: `FocusGuard/tests/test_steuerung.py`

**Interfaces:**
- Consumes: `Einstellungen` (Task 1), `Speicher` (Task 2), `Gedaechtnis` (Task 4), `Entscheider` (Task 6), `Eskalation` (Task 7), `berechne`, `Auswertung` (Task 14), models
- Produces:
  - Protocols: `OberflaechePort` (`hinweis(text: str)`, `overlay_zeigen(titel: str, text: str, quelle: str)`, `overlay_schliessen()`, `icon(farbe: str)`, `tooltip(text: str)`, `zeige_auswertung(a: Auswertung, verlauf: list[Auswertung])`), `SensorPort` (`setze(pc, webcam, smartphone)`, `stoppe()`, `problem() -> str | None`, `kamera_jpeg() -> bytes | None`), `BlockerPort` (`pruefe(b, gesperrt: frozenset[str], fokus: AufgabenListen) -> str | None`), `KiRichterPort` (`einreihen(anfrage, aufgabe)`, `leeren()`)
  - `class Steuerung(einst: Einstellungen, speicher: Speicher, ui: OberflaechePort, sensoren_fabrik: Callable[[Callable[[object], None], Callable[[str, str], None]], SensorPort], blocker: BlockerPort, richter: KiRichterPort | None, uhr: Uhr)` with
    `aktiv: bool` (property), `aufgabe: str | None` (property), `sensoren: tuple[bool, bool, bool]` (property, current checkbox state, initially from `einst.sensoren`),
    `setze_einstellungen(einst) -> None` (used from the next session),
    `starte_session(aufgabe: str, dauer_min: int, listen: AufgabenListen) -> None`,
    `beende_session(vorzeitig: bool, zeigen: bool = True) -> None`,
    `setze_sensoren(pc: bool, webcam: bool, smartphone: bool) -> None`,
    `tick() -> None`,
    `beobachtung(b: object) -> None`, `sensor_fehler(name: str, meldung: str) -> None`, `ki_ergebnis(e: KiErgebnis) -> None` (these three are thread-safe: `queue.SimpleQueue`),
    `zurueck_zur_aufgabe() -> None`, `gehoert_zur_aufgabe(quelle: str) -> None`, `sperren_aufheben() -> None`,
    `verlauf_7_tage() -> list[Auswertung]`,
    `kamera_jpeg() -> bytes | None` (thread-safe; delegates to the running `SensorPort`, `None` without session)

Behaviour of `tick()` without an active session: drain and drop all queues, nothing else. With a session (exact order): (1) drain observations into the Entscheider; for each new `PcBeobachtung` call `blocker.pruefe(b, frozenset(gesperrt), entscheider.listen)` and log `sperre_ausgefuehrt` when it returns an action; (2) drain sensor errors → event `sensor_fehler`; a message `"Sensor dauerhaft ausgeschaltet"` adds the line `"{name}-Sensor ausgeschaltet"` to the tooltip for the rest of the session; (3) drain AI results of the current session only → `entscheider.ki_ergebnis`, persist a returned memory entry, event `ki_aufruf` with `details = {"art", "tokens_ein", "tokens_aus", "fehler"}` and status of the verdict; (4) `richter.einreihen(a, aufgabe)` for every `entscheider.ki_anfragen(jetzt)` (skipped without richter); (5) `u = entscheider.urteil(jetzt)`; event `statuswechsel` when `(status, quelle)` changed; (6) execute `eskalation.schritt(u, jetzt)`; (7) tooltip `"FocusGuard – {aufgabe} – noch {rest} min"` plus `"\n{problem}"` when `sensoren.problem()` is set plus the switched-off sensor lines, only when the text changed; (8) `jetzt >= start + dauer_min*60` → `beende_session(vorzeitig=False)`.

Action execution: `Hinweis(t)` → `ui.hinweis(f"{t} – zurück zu {aufgabe}?")` + event `eskalation` stufe 1; `OverlayZeigen(t, q)` → `ui.overlay_zeigen(f"Zurück zu: {aufgabe}", f"{t}\nFokuszeit bisher: {m} min", q)` (m from `berechne` on the events so far) + event stufe 2; `Sperren(q)` → add to `gesperrt` + event `sperre`; `HandyOverlay()` → `ui.overlay_zeigen("Leg das Handy weg", f"Zurück zu: {aufgabe}", "handy")` + event stufe 3; `OverlaySchliessen()` → `ui.overlay_schliessen()`; `Begruessung(m)` → `ui.hinweis(f"Du warst {m} Minuten weg. Weiter mit {aufgabe}?")`; `IconStatus(f)` → `ui.icon(f)`.

`starte_session`: save lists, load memory, create `Entscheider`, `Eskalation`, session row, event `statuswechsel` (fokus), `sensoren = sensoren_fabrik(self.beobachtung, self.sensor_fehler)` then `.setze(*self.sensoren)`, `ui.icon("gruen")`.
`beende_session`: `sensoren.stoppe()`, `richter.leeren()`, `ui.overlay_schliessen()`, clear `gesperrt`, `ui.icon("grau")`, `ui.tooltip("FocusGuard – keine Session")`, `speicher.beende_session`, if not `vorzeitig`: `ui.hinweis("Session geschafft!")`; if `zeigen`: `ui.zeige_auswertung(berechne(...), verlauf_7_tage())`. Calling it without an active session does nothing.
`setze_sensoren`: store; during a session also `entscheider.setze_sensoren`, `sensoren.setze` and event `checkbox` with details `{"pc", "webcam", "smartphone"}`.
`gehoert_zur_aufgabe(q)`: `entscheider.korrektur` → persist lists/memory; remove `q` from `gesperrt`; execute `eskalation.korrektur(jetzt)`; event `korrektur`.
`zurueck_zur_aufgabe()`: execute `eskalation.zurueck_zur_aufgabe(jetzt)`. `sperren_aufheben()`: clear `gesperrt`, event `sperre_aufgehoben`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_steuerung.py
from focusguard.steuerung import Steuerung
from focusguard.storage import Speicher
from focusguard.clock import TestUhr
from focusguard.models import AufgabenListen, KiArt, KiErgebnis, KiUrteil, Status
from hilfen import pc, einst

class FakeUi:
    def __init__(self): self.log = []
    def __getattr__(self, name): return lambda *a: self.log.append((name, *a))
    def namen(self): return [x[0] for x in self.log]

class FakeSensoren:
    def __init__(self): self.gesetzt, self.gestoppt = [], False
    def setze(self, *a): self.gesetzt.append(a)
    def stoppe(self): self.gestoppt = True
    def problem(self): return None
    def kamera_jpeg(self): return None

class FakeBlocker:
    def __init__(self): self.gesperrt = []
    def pruefe(self, b, gesperrt, fokus): self.gesperrt.append(gesperrt); return None

class FakeRichter:
    def __init__(self): self.anfragen, self.geleert = [], False
    def einreihen(self, a, aufgabe): self.anfragen.append(a)
    def leeren(self): self.geleert = True

def aufbau(dauer=50, richter=True):
    u, ui, sens, bl = TestUhr(1000.0), FakeUi(), FakeSensoren(), FakeBlocker()
    r = FakeRichter() if richter else None
    st = Steuerung(einst(), Speicher(":memory:"), ui, lambda aus, feh: sens, bl, r, u)
    st.starte_session("Blender lernen", dauer, AufgabenListen(fokus_programme=("blender.exe",)))
    return st, u, ui, sens, bl, r

def ticks(st, u, sekunden, beob=None):
    for _ in range(int(sekunden * 4)):
        if beob: st.beobachtung(beob(u()))
        u.vor(0.25); st.tick()

def arten(st): return [e.art for e in st._speicher.ereignisse(st._session.id)]

def test_start():
    st, u, ui, sens, bl, r = aufbau()
    assert st.aktiv and sens.gesetzt == [(True, True, True)] and ("icon", "gruen") in ui.log
    assert arten(st) == ["statuswechsel"]

def test_ablenkung_hinweis_mit_aufgabe():
    st, u, ui, *_ = aufbau()
    ticks(st, u, 11, lambda t: pc(url="https://instagram.com", zeit=t))
    [h] = [x for x in ui.log if x[0] == "hinweis"]
    assert "Blender lernen" in h[1]
    assert "eskalation" in arten(st)

def test_unklare_seite_eingereiht_und_ergebnis_gespeichert():
    st, u, ui, sens, bl, r = aufbau()
    ticks(st, u, 1, lambda t: pc(url="https://example.org", titel="T", zeit=t))
    [a] = r.anfragen; assert a.art is KiArt.SEITE
    st.ki_ergebnis(KiErgebnis(a, KiUrteil(Status.FOKUS, "passt", 0.9, "seite"), None, 1000, 20))
    ticks(st, u, 0.25)
    assert len(st._speicher.lade_gedaechtnis("blender lernen")) == 1 and "ki_aufruf" in arten(st)

def test_ohne_richter_keine_anfragen():
    st, u, *_ = aufbau(richter=False)
    ticks(st, u, 1, lambda t: pc(url="https://example.org", zeit=t))   # must not raise

def test_stufe3_sperrt_und_aufheben():
    st, u, ui, sens, bl, r = aufbau()
    ticks(st, u, 72, lambda t: pc(url="https://instagram.com", zeit=t))
    assert "domain:instagram.com" in bl.gesperrt[-1]
    st.sperren_aufheben(); ticks(st, u, 0.25, lambda t: pc(url="https://instagram.com", zeit=t))
    assert bl.gesperrt[-1] == frozenset() and "sperre_aufgehoben" in arten(st)

def test_gehoert_zur_aufgabe():
    st, u, ui, *_ = aufbau()
    ticks(st, u, 45, lambda t: pc(url="https://instagram.com", zeit=t))
    st.gehoert_zur_aufgabe("domain:instagram.com")
    assert "instagram.com" in st._speicher.lade_listen("blender lernen").fokus_domains
    assert ui.namen()[-2:] == ["overlay_schliessen", "icon"] and "korrektur" in arten(st)

def test_session_endet_nach_ablauf():
    st, u, ui, sens, *_ = aufbau(dauer=1)
    ticks(st, u, 61)
    assert not st.aktiv and sens.gestoppt and ("hinweis", "Session geschafft!") in ui.log and "zeige_auswertung" in ui.namen()
    [s] = st._speicher.sessions_seit(0); assert s.vorzeitig_beendet is False

def test_vorzeitig_beenden_schliesst_overlay_und_hebt_sperren_auf():
    st, u, ui, sens, bl, r = aufbau()
    ticks(st, u, 72, lambda t: pc(url="https://instagram.com", zeit=t))
    st.beende_session(vorzeitig=True)
    assert "overlay_schliessen" in ui.namen() and ("icon", "grau") in ui.log and sens.gestoppt and r.geleert
    assert ("hinweis", "Session geschafft!") not in ui.log
    [s] = st._speicher.sessions_seit(0); assert s.vorzeitig_beendet is True
    st.beende_session(vorzeitig=True)                       # second call is a no-op

def test_checkbox_und_sensorfehler():
    st, u, ui, sens, *_ = aufbau()
    st.setze_sensoren(True, False, True); st.sensor_fehler("kamera", "kaputt"); ticks(st, u, 0.25)
    assert sens.gesetzt[-1] == (True, False, True) and {"checkbox", "sensor_fehler"} <= set(arten(st))
    st.sensor_fehler("kamera", "Sensor dauerhaft ausgeschaltet"); ticks(st, u, 0.25)
    assert "kamera-Sensor ausgeschaltet" in [x for x in ui.log if x[0] == "tooltip"][-1][1]

def test_ki_ergebnis_nach_sessionende_ignoriert():
    st, u, ui, sens, bl, r = aufbau()
    ticks(st, u, 1, lambda t: pc(url="https://example.org", zeit=t)); [a] = r.anfragen
    st.beende_session(vorzeitig=True)
    st.ki_ergebnis(KiErgebnis(a, KiUrteil(Status.FOKUS, "x", 0.9, "seite"), None)); st.tick()  # must not raise
```

The tests read the private attributes `_speicher` and `_session`; name them exactly so.

- [ ] **Step 2: Run tests to verify they fail** — `python -m pytest tests/test_steuerung.py -v` → FAIL

- [ ] **Step 3: Implement `Steuerung`**

- [ ] **Step 4: Run tests to verify they pass** — `python -m pytest -v` (whole suite) → PASS

- [ ] **Step 5: Commit**

```bash
git add FocusGuard/focusguard/steuerung.py FocusGuard/tests/test_steuerung.py
git commit -m "feat(focusguard): Steuerung wiring decision, escalation, blocker and UI ports"
```

---

### Task 16: User interface (PySide6)

**Files:**
- Create: `FocusGuard/focusguard/ui/__init__.py`, `ui/icons.py`, `ui/overlay.py`, `ui/start_dialog.py`, `ui/report.py`, `ui/tray.py`
- Test: `FocusGuard/tests/test_ui.py`

**Interfaces:**
- Consumes: `AufgabenListen` (Task 1), `Auswertung`, `Status` (Task 14), `OberflaechePort` (Task 15)
- Produces:
  - `icons.py`: `FARBEN = {"grau": "#8a8a8a", "gruen": "#2e9d4f", "gelb": "#e0a800", "rot": "#d64545", "blau": "#3d7bd9"}`, `farbiges_icon(farbe: str) -> QIcon` (filled circle, 64 px)
  - `overlay.py`: `class Overlay(zurueck: Callable[[], None], gehoert: Callable[[str], None])` with `zeige(titel: str, text: str, quelle: str) -> None` (one frameless, always-on-top, `Qt.Tool` window per `QGuiApplication.screens()`, dark background at 92 % opacity, title + text + two buttons on the primary screen: `"Zurück zur Aufgabe"` → `zurueck()`, `"Gehört zur Aufgabe"` → `gehoert(quelle)`; Esc on any window → `zurueck()`; both buttons also close the overlay), `schliesse() -> None`, property `ist_offen -> bool`
  - `start_dialog.py`: `class StartDialog(QDialog)(gespeicherte_listen: Callable[[str], AufgabenListen | None], vorschlagen: Callable[[str], AufgabenListen | None], ausfuehren: Callable[[Callable[[], None]], None] | None = None)`; page 1: `QLineEdit` aufgabe (`objectName "aufgabe"`), `QComboBox` with `25`, `50`, `90`, `"frei"` + `QSpinBox` (1–240) enabled only for "frei", button `"Weiter"` (disabled while the task is empty); page 2: four `QPlainTextEdit` (one entry per line) titled "Fokus-Programme", "Fokus-Domains", "Ablenkende Programme", "Ablenkende Domains", label `"KI schlägt Listen vor …"` while waiting, button `"Session starten"`. "Weiter" fills from `gespeicherte_listen(aufgabe)` if it returns non-empty lists, otherwise runs `vorschlagen(aufgabe)` via `ausfuehren` (default: a daemon thread) and fills the fields through a Qt signal; `None` leaves the fields empty. `ergebnis() -> tuple[str, int, AufgabenListen] | None` after `exec()`.
  - `report.py`: `class AuswertungsFenster(QDialog)(a: Auswertung, verlauf: list[Auswertung])` — labels for Fokusquote (`"{q:.0%}"` or `"–"`), minutes per status, top distractions, escalations per stage, blocks/lifts, corrections, AI calls and `"ca. {kosten:.2f} $"`, `"vorzeitig beendet nach {dauer} von {geplant} min"` when applicable; `QTableWidget` for the last 7 days (Datum, Aufgabe, Dauer, Fokusquote)
  - `tray.py`: `class Tray(QSystemTrayIcon)` implementing `OberflaechePort`, constructed with callbacks `bei_start()`, `bei_ende()`, `bei_sensor(name: str, wert: bool)` (name ∈ `"pc"`, `"webcam"`, `"smartphone"`), `bei_aufheben()`, `bei_einstellungen()`, `bei_auswertung()`, `bei_beenden()`, `zurueck()`, `gehoert(quelle)` and initial `sensoren: tuple[bool, bool, bool]`. Menu order: `Session starten …`, `Session beenden`, separator, checkable `PC`, `Webcam`, `Smartphone`, separator, `Sperren aufheben`, `Einstellungen …`, `Auswertung …`, separator, `Beenden`. `setze_session_aktiv(aktiv: bool)` enables/disables start, end and "Sperren aufheben". `hinweis` → `showMessage("FocusGuard", text)` plus `winsound.MessageBeep()` on Windows; `overlay_*` → `Overlay`; `icon(f)` → `setIcon(farbiges_icon(f))`; `zeige_auswertung` → `AuswertungsFenster(...).show()` (kept referenced)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ui.py
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from focusguard.models import AufgabenListen, Status
from focusguard.auswertung import Auswertung

@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

def knopf(widget, text):
    return next(b for b in widget.findChildren(QtWidgets.QPushButton) if b.text() == text)

def test_overlay_knoepfe_und_esc(app):
    from focusguard.ui.overlay import Overlay
    log = []
    o = Overlay(lambda: log.append("zurueck"), lambda q: log.append(q))
    o.zeige("Zurück zu: Blender", "Instagram", "domain:instagram.com"); assert o.ist_offen
    knopf(o.fenster[0], "Gehört zur Aufgabe").click()
    assert log == ["domain:instagram.com"] and not o.ist_offen
    o.zeige("t", "x", "q"); QTest.keyClick(o.fenster[0], Qt.Key_Escape)
    assert log[-1] == "zurueck" and not o.ist_offen

def test_start_dialog_mit_vorschlag(app):
    from focusguard.ui.start_dialog import StartDialog
    d = StartDialog(lambda a: None, lambda a: AufgabenListen(fokus_programme=("blender.exe",)), ausfuehren=lambda f: f())
    assert not knopf(d, "Weiter").isEnabled()
    d.findChild(QtWidgets.QLineEdit, "aufgabe").setText("Blender lernen")
    knopf(d, "Weiter").click(); app.processEvents()
    knopf(d, "Session starten").click()
    aufgabe, dauer, listen = d.ergebnis()
    assert (aufgabe, dauer, listen.fokus_programme) == ("Blender lernen", 25, ("blender.exe",))

def test_start_dialog_nutzt_gespeicherte_listen(app):
    from focusguard.ui.start_dialog import StartDialog
    aufrufe = []
    d = StartDialog(lambda a: AufgabenListen(fokus_domains=("blender.org",)), lambda a: aufrufe.append(a), ausfuehren=lambda f: f())
    d.findChild(QtWidgets.QLineEdit, "aufgabe").setText("Blender lernen")
    assert knopf(d, "Weiter").isEnabled()
    knopf(d, "Weiter").click(); knopf(d, "Session starten").click()
    assert d.ergebnis()[2].fokus_domains == ("blender.org",) and aufrufe == []

def test_auswertungsfenster(app):
    from focusguard.ui.report import AuswertungsFenster
    a = Auswertung(1, "Blender", 0.0, 12, 50, True, {Status.FOKUS: 600.0}, 0.83, [("domain:instagram.com", 2, 90.0)], {1: 2}, 1, 0, 0, 5, 0.01)
    f = AuswertungsFenster(a, [a])
    texte = " ".join(l.text() for l in f.findChildren(QtWidgets.QLabel))
    assert "83%" in texte and "vorzeitig beendet nach 12 von 50 min" in texte

def test_tray_menue(app):
    from focusguard.ui.tray import Tray
    log = []
    cb = {n: (lambda *a, n=n: log.append((n, *a))) for n in
          ("bei_start", "bei_ende", "bei_sensor", "bei_aufheben", "bei_einstellungen", "bei_auswertung", "bei_beenden", "zurueck", "gehoert")}
    t = Tray(sensoren=(True, True, False), **cb)
    texte = [a.text() for a in t.contextMenu().actions() if a.text()]
    assert texte == ["Session starten …", "Session beenden", "PC", "Webcam", "Smartphone", "Sperren aufheben", "Einstellungen …", "Auswertung …", "Beenden"]
    smartphone = next(a for a in t.contextMenu().actions() if a.text() == "Smartphone")
    assert not smartphone.isChecked(); smartphone.trigger()
    assert log[-1] == ("bei_sensor", "smartphone", True)
    t.setze_session_aktiv(False)
    assert not next(a for a in t.contextMenu().actions() if a.text() == "Session beenden").isEnabled()
```

`Overlay` exposes its windows as attribute `fenster: list[QWidget]` (primary screen first).

- [ ] **Step 2: Run tests to verify they fail** — `python -m pytest tests/test_ui.py -v` → FAIL (`ModuleNotFoundError`); if it reports SKIPPED, PySide6 or its system libraries are missing: install `libegl1 libgl1 libxkbcommon0 libfontconfig1` (or report that UI tests are skipped in this environment) before continuing.

- [ ] **Step 3: Implement the UI modules**

- [ ] **Step 4: Run tests to verify they pass** — `python -m pytest tests/test_ui.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add FocusGuard/focusguard/ui FocusGuard/tests/test_ui.py
git commit -m "feat(focusguard): tray, start dialog, overlay and report window"
```

---

### Task 17: App start, checks, README

**Files:**
- Create: `FocusGuard/focusguard/app.py`, `FocusGuard/focusguard/__main__.py`, `FocusGuard/start_focusguard.bat`, `FocusGuard/README.md`, `FocusGuard/tools/ki_check.py`
- Test: `FocusGuard/tests/test_app.py`, `FocusGuard/tests/test_ki_check.py`

**Interfaces:**
- Consumes: everything above
- Produces:
  - `app.py`: `main(argv: list[str] | None = None) -> int`. Flags: none → tray app; `--pruefen` → `pruefen() -> int`; `--kamera-test` → `kamera_test() -> int`.
    Tray app wiring: `QApplication` with `setQuitOnLastWindowClosed(False)`; `datenordner()`; `lade_einstellungen` (on `EinstellungsFehler`: defaults + `hinweis` with the message); `Speicher(datenordner()/"focusguard.db")`; if `ANTHROPIC_API_KEY` is unset → `richter = None` and `hinweis("ANTHROPIC_API_KEY fehlt – FocusGuard läuft nur mit Regeln.")`; else `KiRichter(anthropic_sender(), Bildschirm(<camera jpeg of the running camera sensor or None>), einst.ki.modell, einst.ki.min_sicherheit, einst.ki.max_aufrufe_pro_minute, time.time, ablage=datenordner()/"bilder" if einst.ki.bilder_speichern else None)` plus a daemon worker thread looping `verarbeite_naechste()` → `steuerung.ki_ergebnis`, sleeping 0.5 s when it returns `None`; `Steuerung(..., sensoren_fabrik=lambda aus, feh: standard_verwaltung(aus, feh, datenordner()), blocker=windows_blocker(...) on win32 else a no-op blocker, ...)`; `QTimer` 250 ms → `steuerung.tick()`; `QFileSystemWatcher` on `settings.toml` → reload → `steuerung.setze_einstellungen` (error → `hinweis`, keep old); tray callbacks: start → `StartDialog(lambda a: <stored lists or None>, richter.startlisten if richter else lambda a: None)` → `starte_session`; end → `beende_session(vorzeitig=True)`; sensor → `setze_sensor(...)` + `steuerung.setze_sensoren`; einstellungen → `QDesktopServices.openUrl(QUrl.fromLocalFile(...))`; auswertung → last session's report; beenden → `beende_session(vorzeitig=True, zeigen=False)` then `app.quit()`.
  - `pruefen() -> int`: prints one line per check — `Python >= 3.12`, each package importable (`PySide6`, `mediapipe`, `cv2`, `mss`, `anthropic`, and on Windows `win32gui`, `uiautomation`), `ANTHROPIC_API_KEY gesetzt`, `Datenordner beschreibbar`, `Modelle vorhanden` (missing models are downloaded via `stelle_modell_bereit` first), `Kamera erreichbar` — as `"[OK] <name>"` or `"[FEHLT] <name>: <grund>"`; returns 0 if all OK, else 1.
  - `app.py` passes `Bildschirm(steuerung.kamera_jpeg)` to the `KiRichter`.
  - `kamera_test() -> int`: opens the camera with face and phone analysis and prints `Gesicht: ja/nein  Pitch: 12.3°  Handy: 0.81` twice per second until Ctrl+C.
  - `tools/ki_check.py`: `lade_faelle(pfad: Path) -> list[dict]` reading `<ordner>/erwartet.toml` (`[[fall]]` with `datei`, `art` ∈ `seite|handy|stichprobe`, `aufgabe`, `erwartet` ∈ `fokus|abgelenkt`, optional `prozess`, `titel`, `url`); `pruefe(faelle: list[dict], ordner: Path, sender: Sender, modell: str) -> tuple[int, int]` (treffer, gesamt) printing one line per case; `if __name__ == "__main__"`: `python tools/ki_check.py <ordner>` with `anthropic_sender()`.
  - `start_focusguard.bat`: `cd /d %~dp0`, activate `.venv\Scripts\activate.bat`, run `pythonw -m focusguard`.
  - `README.md` (German): requirements; installation (`py -3.12 -m venv .venv`, `.venv\Scripts\activate`, `pip install -e .`); setting `ANTHROPIC_API_KEY` (`setx ANTHROPIC_API_KEY "…"`, new terminal); `python -m focusguard --pruefen`; `python -m focusguard --kamera-test`; starting via `start_focusguard.bat`; where data lives; how `ki_check.py` works; and this Windows test checklist:
    1. `--pruefen` shows only `[OK]`.
    2. `--kamera-test`: face yes/no switches when you leave; pitch rises clearly when you lower your head; phone score > 0.5 when you hold your phone.
    3. Tray icon appears grey; the menu shows all entries; checkboxes survive a restart.
    4. Start a 25-minute session "Blender lernen": the list page shows AI suggestions.
    5. Blender in front → icon stays green; Chrome with docs.blender.org → green.
    6. instagram.com in Chrome, Edge and Firefox → notification after ~10 s, overlay after ~40 s on all monitors, tab closed after ~70 s.
    7. "Gehört zur Aufgabe" on the overlay → the site stays allowed for this task.
    8. YouTube tutorial on Blender vs. an unrelated video → different verdicts (check the tooltip/report).
    9. Hold the phone and look down for 3 s → notification; keep it → overlay "Leg das Handy weg", closes 5 s after putting it away.
    10. Leave for 6 minutes → icon blue, greeting on return.
    11. Video on the second monitor while Blender is in front → flagged within ~2.5 minutes.
    12. Close Teams/another app's camera use: start a call in Teams → tooltip shows "Kamera nicht verfügbar", no absence.
    13. "Sperren aufheben" and "Beenden" work at once at any stage; the report opens after a session.
    14. Edit `settings.toml` with a typo → notification, app keeps running.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_app.py
import subprocess, sys

def test_pruefen_meldet_fehlenden_schluessel(tmp_path):
    (tmp_path / "modelle").mkdir()
    for name in ("face_landmarker.task", "efficientdet_lite0.tflite"):   # avoid downloads in the test
        (tmp_path / "modelle" / name).write_bytes(b"x")
    env = {"FOCUSGUARD_HOME": str(tmp_path), "PATH": "", "QT_QPA_PLATFORM": "offscreen"}
    r = subprocess.run([sys.executable, "-m", "focusguard", "--pruefen"], capture_output=True, text=True, env=env, timeout=120)
    assert "[FEHLT] ANTHROPIC_API_KEY gesetzt" in r.stdout and "[OK] Python >= 3.12" in r.stdout
    assert "[OK] Modelle vorhanden" in r.stdout and r.returncode == 1
```

```python
# tests/test_ki_check.py
import importlib.util, json, pathlib
from focusguard.ai.client import KiRohAntwort

spec = importlib.util.spec_from_file_location("ki_check", pathlib.Path(__file__).parents[1] / "tools" / "ki_check.py")
ki_check = importlib.util.module_from_spec(spec); spec.loader.exec_module(ki_check)

def test_pruefe_zaehlt_treffer(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"\xff\xd8x"); (tmp_path / "b.jpg").write_bytes(b"\xff\xd8y")
    (tmp_path / "erwartet.toml").write_text(
        '[[fall]]\ndatei = "a.jpg"\nart = "seite"\naufgabe = "Blender"\nerwartet = "fokus"\nprozess = "blender.exe"\n'
        '[[fall]]\ndatei = "b.jpg"\nart = "handy"\naufgabe = "Blender"\nerwartet = "abgelenkt"\n')
    antwort = json.dumps({"status": "fokus", "begruendung": "x", "sicherheit": 0.9, "gilt_fuer": "seite"})
    faelle = ki_check.lade_faelle(tmp_path)
    assert ki_check.pruefe(faelle, tmp_path, lambda kw: KiRohAntwort(antwort, 1, 1), "claude-haiku-5-5") == (1, 2)
```

- [ ] **Step 2: Run tests to verify they fail** — `python -m pytest tests/test_app.py tests/test_ki_check.py -v` → FAIL

- [ ] **Step 3: Implement `app.py`, `__main__.py`, `tools/ki_check.py`, `start_focusguard.bat`, `README.md`** (`pruefen` must not open a window; camera check skips gracefully when no camera exists)

- [ ] **Step 4: Run the whole suite** — `python -m pytest -v` → all PASS (UI tests may be SKIPPED only if PySide6 cannot load here; say so in the report)

- [ ] **Step 5: Smoke-start the app headless** — `QT_QPA_PLATFORM=offscreen FOCUSGUARD_HOME=$(mktemp -d) timeout 5 python -m focusguard; echo $?` → exit `124` (killed by timeout, i.e. it kept running) with no traceback on stderr

- [ ] **Step 6: Commit and push**

```bash
git add FocusGuard
git commit -m "feat(focusguard): app wiring, self-check, camera test, AI check tool and README"
git push -u origin claude/serene-hamilton-sjzb16
```
