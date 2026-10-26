"""Prompts, JSON-Schemas und Auswertung der KI-Antworten."""

from __future__ import annotations

import base64
import json

from ..decision.rules import MISCH_PLATTFORMEN, domain_aus_url, ist_misch_plattform  # noqa: F401
from ..models import AufgabenListen, KiUrteil, PcBeobachtung, Status

SYSTEM_URTEIL = """\
Du bist der Fokus-Assistent einer Lern-App. Die Person hat sich eine Aufgabe vorgenommen und dich gebeten, ehrlich zu beurteilen, ob sie gerade daran arbeitet. Beurteile nur, was du auf den Bildern und in den Angaben siehst.
- fokus: Die Tätigkeit dient der Aufgabe, auch Recherche, Dokumentation, Tutorials, Notizen oder Hintergrundmusik.
- abgelenkt: Die Tätigkeit hat mit der Aufgabe nichts zu tun, etwa Social Media, Unterhaltung, Nachrichten, Shopping, Spiele oder Handy-Nutzung.
- unklar: Du kannst es nicht sicher sagen.
gilt_fuer: "domain" nur, wenn die ganze Website eindeutig zur Aufgabe passt oder eindeutig ablenkt. "programm" nur, wenn das ganze Programm eindeutig passt oder ablenkt. Sonst "seite".
sicherheit: Zahl von 0 bis 1.
begruendung: ein kurzer Satz auf Deutsch, direkt an die Person gerichtet (du)."""

SYSTEM_STARTLISTEN = """\
Du hilfst einer Lern-App, Listen für eine Fokus-Session anzulegen. Nenne Windows-Programme (Prozessnamen wie blender.exe) und Domains (wie docs.blender.org), die eindeutig zur Aufgabe gehören, und solche, die bei dieser Aufgabe eindeutig ablenken. Gemischte Plattformen wie youtube.com, reddit.com, x.com oder google.com nimmst du in keine Liste auf. Höchstens 10 Einträge pro Liste."""

STICHPROBE_REGEL = """\
So beurteilst du die Stichprobe: Entscheidend ist, was die Person im aktiven Fenster tut. Andere Monitore sprechen \
nur dann für abgelenkt, wenn dort sichtbar etwas läuft, das sie nebenbei konsumiert, etwa ein abspielendes Video, \
ein Stream oder ein Spiel. Offene, ruhende Fenster auf anderen Monitoren, etwa ein Messenger, eine Kursseite, ein \
Shop oder andere Dokumente, sind für sich keine Ablenkung.
"""

_STATUS = ("fokus", "abgelenkt", "unklar")
_GILT_FUER = ("seite", "domain", "programm")

URTEIL_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": list(_STATUS)},
        "begruendung": {"type": "string"},
        "sicherheit": {"type": "number"},
        "gilt_fuer": {"type": "string", "enum": list(_GILT_FUER)},
    },
    "required": ["status", "begruendung", "sicherheit", "gilt_fuer"],
    "additionalProperties": False,
}

_LISTEN = ("fokus_programme", "fokus_domains", "ablenkung_programme", "ablenkung_domains")

STARTLISTEN_SCHEMA = {
    "type": "object",
    "properties": {name: {"type": "array", "items": {"type": "string"}} for name in _LISTEN},
    "required": list(_LISTEN),
    "additionalProperties": False,
}

class KiAntwortFehler(Exception):
    pass


def bild_block(jpeg: bytes) -> dict:
    return {"type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg",
                       "data": base64.standard_b64encode(jpeg).decode("ascii")}}


def _text(text: str) -> dict:
    return {"type": "text", "text": text}


def _fenster_zeilen(pc: PcBeobachtung) -> str:
    return (f"Programm: {pc.prozess}\nFenstertitel: {pc.fenstertitel}\n"
            f"URL: {pc.url or 'unbekannt'}\n")


def startlisten_inhalt(aufgabe: str) -> list[dict]:
    return [_text(f"Aufgabe: {aufgabe}")]


def seite_inhalt(aufgabe: str, pc: PcBeobachtung, bild: bytes | None) -> list[dict]:
    bloecke = [bild_block(bild)] if bild else []
    bloecke.append(_text(f"Aufgabe: {aufgabe}\n{_fenster_zeilen(pc)}Passt das gerade zur Aufgabe?"))
    return bloecke


def handy_inhalt(aufgabe: str, bild: bytes) -> list[dict]:
    return [bild_block(bild),
            _text(f"Aufgabe: {aufgabe}\nDas Webcam-Bild zeigt die Person am Schreibtisch, ein Handy wurde erkannt. "
                  "Benutzt die Person das Handy gerade (abgelenkt), oder liegt es nur da bzw. dient es der "
                  "Aufgabe (fokus)?")]


def stichprobe_inhalt(aufgabe: str, pc: PcBeobachtung | None, monitore: list[bytes],
                      webcam: bytes | None) -> list[dict]:
    bloecke: list[dict] = []
    zeilen = [f"Aufgabe: {aufgabe}"]
    for m, bild in enumerate(monitore, start=1):
        bloecke.append(bild_block(bild))
        zeilen.append(f"Bild {len(bloecke)}: Monitor {m}")
    if webcam:
        bloecke.append(bild_block(webcam))
        zeilen.append(f"Bild {len(bloecke)}: Webcam")
    text = "\n".join(zeilen) + "\n"
    if pc is not None:
        text += "Aktives Fenster:\n" + _fenster_zeilen(pc)
    text += STICHPROBE_REGEL + "Arbeitet die Person gerade an der Aufgabe?"
    bloecke.append(_text(text))
    return bloecke


def baue_anfrage(modell: str, system: str, inhalt: list[dict], schema: dict) -> dict:
    return {
        "model": modell,
        "max_tokens": 2048,
        "system": system,
        "messages": [{"role": "user", "content": inhalt}],
        "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": schema}},
    }


def _lade_json_objekt(text: str) -> dict:
    try:
        daten = json.loads(text)
    except (json.JSONDecodeError, TypeError) as e:
        raise KiAntwortFehler(f"Antwort ist kein JSON: {e}") from e
    if not isinstance(daten, dict):
        raise KiAntwortFehler("Antwort ist kein JSON-Objekt")
    return daten


def parse_urteil(text: str, min_sicherheit: float) -> KiUrteil:
    daten = _lade_json_objekt(text)
    status, begruendung = daten.get("status"), daten.get("begruendung")
    sicherheit, gilt_fuer = daten.get("sicherheit"), daten.get("gilt_fuer")
    if status not in _STATUS:
        raise KiAntwortFehler(f"Unbekannter Status: {status!r}")
    if gilt_fuer not in _GILT_FUER:
        raise KiAntwortFehler(f"Unbekanntes gilt_fuer: {gilt_fuer!r}")
    if not isinstance(begruendung, str):
        raise KiAntwortFehler("begruendung fehlt")
    if isinstance(sicherheit, bool) or not isinstance(sicherheit, (int, float)):
        raise KiAntwortFehler("sicherheit fehlt")
    sicherheit = min(1.0, max(0.0, float(sicherheit)))
    s = Status(status)
    if sicherheit < min_sicherheit:
        s = Status.UNKLAR
    return KiUrteil(s, begruendung.strip(), sicherheit, gilt_fuer)


def parse_startlisten(text: str) -> AufgabenListen:
    daten = _lade_json_objekt(text)
    werte: dict[str, tuple[str, ...]] = {}
    for name in _LISTEN:
        roh = daten.get(name, [])
        if not isinstance(roh, list):
            raise KiAntwortFehler(f"{name} ist keine Liste")
        gesehen: list[str] = []
        for eintrag in roh:
            if not isinstance(eintrag, str):
                continue
            if name.endswith("domains"):
                wert = domain_aus_url(eintrag)
                if wert is None or ist_misch_plattform(wert):
                    continue
            else:
                wert = eintrag.strip().lower()
                if not wert:
                    continue
            if wert not in gesehen:
                gesehen.append(wert)
        werte[name] = tuple(gesehen)
    return AufgabenListen(**werte)
