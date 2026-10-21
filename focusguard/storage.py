"""SQLite-Ablage für Sessions, Ereignisse, KI-Gedächtnis und aufgabenbezogene Listen.

Wird nur aus dem Qt-Hauptthread benutzt.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import AufgabenListen, Ereignis, GedaechtnisEintrag, Session, Status

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aufgabe TEXT NOT NULL,
    aufgabe_key TEXT NOT NULL,
    start REAL NOT NULL,
    geplant_min INTEGER NOT NULL,
    ende REAL,
    vorzeitig_beendet INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ereignisse (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    zeit REAL NOT NULL,
    art TEXT NOT NULL,
    quelle TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    details TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ereignisse_session ON ereignisse (session_id, zeit);
CREATE TABLE IF NOT EXISTS gedaechtnis (
    aufgabe_key TEXT NOT NULL,
    ebene TEXT NOT NULL,
    schluessel TEXT NOT NULL,
    status TEXT NOT NULL,
    begruendung TEXT NOT NULL,
    sicherheit REAL NOT NULL,
    zeit REAL NOT NULL,
    UNIQUE (aufgabe_key, ebene, schluessel)
);
CREATE TABLE IF NOT EXISTS listen (
    aufgabe_key TEXT NOT NULL,
    art TEXT NOT NULL,
    typ TEXT NOT NULL,
    wert TEXT NOT NULL,
    reihenfolge INTEGER NOT NULL
);
"""

_LISTEN_FELDER = {
    ("fokus", "programm"): "fokus_programme",
    ("fokus", "domain"): "fokus_domains",
    ("ablenkung", "programm"): "ablenkung_programme",
    ("ablenkung", "domain"): "ablenkung_domains",
}


class Speicher:
    def __init__(self, pfad: Path | str):
        self._db = sqlite3.connect(str(pfad))
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def neue_session(self, s: Session) -> int:
        cur = self._db.execute(
            "INSERT INTO sessions (aufgabe, aufgabe_key, start, geplant_min, ende, vorzeitig_beendet) VALUES (?, ?, ?, ?, ?, ?)",
            (s.aufgabe, s.aufgabe_key, s.start, s.geplant_min, s.ende, int(s.vorzeitig_beendet)))
        self._db.commit()
        return cur.lastrowid

    def beende_session(self, session_id: int, ende: float, vorzeitig: bool) -> None:
        self._db.execute("UPDATE sessions SET ende = ?, vorzeitig_beendet = ? WHERE id = ?",
                         (ende, int(vorzeitig), session_id))
        self._db.commit()

    def sessions_seit(self, zeit: float) -> list[Session]:
        zeilen = self._db.execute(
            "SELECT id, aufgabe, aufgabe_key, start, geplant_min, ende, vorzeitig_beendet FROM sessions "
            "WHERE start >= ? ORDER BY start, id", (zeit,)).fetchall()
        return [Session(z[0], z[1], z[2], z[3], z[4], z[5], bool(z[6])) for z in zeilen]

    def ereignis(self, session_id: int, zeit: float, art: str, quelle: str = "", status: str = "",
                 details: dict | None = None) -> None:
        self._db.execute(
            "INSERT INTO ereignisse (session_id, zeit, art, quelle, status, details) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, zeit, art, quelle, status, json.dumps(details or {}, ensure_ascii=False)))
        self._db.commit()

    def ereignisse(self, session_id: int) -> list[Ereignis]:
        zeilen = self._db.execute(
            "SELECT zeit, art, quelle, status, details FROM ereignisse WHERE session_id = ? ORDER BY zeit, id",
            (session_id,)).fetchall()
        return [Ereignis(z[0], z[1], z[2], z[3], json.loads(z[4])) for z in zeilen]

    def lade_gedaechtnis(self, aufgabe_key: str) -> list[GedaechtnisEintrag]:
        zeilen = self._db.execute(
            "SELECT aufgabe_key, ebene, schluessel, status, begruendung, sicherheit, zeit FROM gedaechtnis "
            "WHERE aufgabe_key = ?", (aufgabe_key,)).fetchall()
        return [GedaechtnisEintrag(z[0], z[1], z[2], Status(z[3]), z[4], z[5], z[6]) for z in zeilen]

    def speichere_gedaechtnis(self, e: GedaechtnisEintrag) -> None:
        self._db.execute(
            "INSERT INTO gedaechtnis (aufgabe_key, ebene, schluessel, status, begruendung, sicherheit, zeit) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (aufgabe_key, ebene, schluessel) DO UPDATE SET "
            "status = excluded.status, begruendung = excluded.begruendung, sicherheit = excluded.sicherheit, "
            "zeit = excluded.zeit",
            (e.aufgabe_key, e.ebene, e.schluessel, e.status.value, e.begruendung, e.sicherheit, e.zeit))
        self._db.commit()

    def lade_listen(self, aufgabe_key: str) -> AufgabenListen:
        werte: dict[str, list[str]] = {feld: [] for feld in _LISTEN_FELDER.values()}
        for art, typ, wert in self._db.execute(
                "SELECT art, typ, wert FROM listen WHERE aufgabe_key = ? ORDER BY reihenfolge", (aufgabe_key,)):
            feld = _LISTEN_FELDER.get((art, typ))
            if feld:
                werte[feld].append(wert)
        return AufgabenListen(**{k: tuple(v) for k, v in werte.items()})

    def speichere_listen(self, aufgabe_key: str, listen: AufgabenListen) -> None:
        self._db.execute("DELETE FROM listen WHERE aufgabe_key = ?", (aufgabe_key,))
        zeilen = []
        for (art, typ), feld in _LISTEN_FELDER.items():
            for i, wert in enumerate(getattr(listen, feld)):
                zeilen.append((aufgabe_key, art, typ, wert, i))
        self._db.executemany("INSERT INTO listen (aufgabe_key, art, typ, wert, reihenfolge) VALUES (?, ?, ?, ?, ?)",
                             zeilen)
        self._db.commit()

    def schliesse(self) -> None:
        self._db.close()
