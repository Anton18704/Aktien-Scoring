"""Dauerhafter Speicher in einer SQLite-Datei (aktien.db).

Analysen werden nie überschrieben: jede Analyse ist ein neuer Eintrag.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from kern.konfig import PROJEKT

DB_DATEI = PROJEKT / "aktien.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS titel (
    ticker          TEXT PRIMARY KEY,
    cik             INTEGER,
    name            TEXT,
    sic             TEXT,
    sic_beschreibung TEXT,
    sektor_auto     TEXT,
    sektor_manuell  TEXT,
    waehrung        TEXT,
    angelegt        TEXT
);
CREATE TABLE IF NOT EXISTS analysen (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT NOT NULL REFERENCES titel(ticker) ON DELETE CASCADE,
    zeitpunkt   TEXT NOT NULL,
    waehrung    TEXT,
    hinweise    TEXT
);
CREATE TABLE IF NOT EXISTS kennzahlen (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    analyse_id  INTEGER NOT NULL REFERENCES analysen(id) ON DELETE CASCADE,
    schluessel  TEXT NOT NULL,
    kategorie   TEXT NOT NULL,
    rohwert     REAL,
    fixpunkte   REAL,
    punkte_damals REAL,
    quelle      TEXT,
    datenstand  TEXT,
    grund       TEXT,
    details     TEXT,
    hinweis     TEXT
);
CREATE TABLE IF NOT EXISTS einschaetzungen (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT NOT NULL REFERENCES titel(ticker) ON DELETE CASCADE,
    zeitpunkt   TEXT NOT NULL,
    f1 REAL, f2 REAL, f3 REAL, f4 REAL,
    begruendung TEXT NOT NULL,
    gegenthese  TEXT
);
CREATE TABLE IF NOT EXISTS einstellungen (
    schluessel  TEXT PRIMARY KEY,
    wert        TEXT
);
CREATE INDEX IF NOT EXISTS ix_analysen_ticker ON analysen(ticker);
CREATE INDEX IF NOT EXISTS ix_kennzahlen_analyse ON kennzahlen(analyse_id);
"""


def jetzt() -> str:
    return datetime.now().isoformat(timespec="seconds")


def verbinden(pfad: Path | str = DB_DATEI) -> sqlite3.Connection:
    con = sqlite3.connect(pfad, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    _migrieren(con)
    return con


def _migrieren(con) -> None:
    """Ältere Datenbanken um neue Spalten ergänzen (bestehende Daten bleiben erhalten)."""
    spalten = {r["name"] for r in con.execute("PRAGMA table_info(einschaetzungen)")}
    if "gegenthese" not in spalten:
        con.execute("ALTER TABLE einschaetzungen ADD COLUMN gegenthese TEXT")
        con.commit()


# ---------------------------------------------------------------- Titel

def titel_speichern(con, ticker, cik, name, sic, sic_beschreibung, sektor_auto, waehrung) -> None:
    con.execute(
        """INSERT INTO titel (ticker, cik, name, sic, sic_beschreibung, sektor_auto, waehrung, angelegt)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(ticker) DO UPDATE SET cik=excluded.cik, name=excluded.name, sic=excluded.sic,
               sic_beschreibung=excluded.sic_beschreibung, sektor_auto=excluded.sektor_auto,
               waehrung=excluded.waehrung""",
        (ticker, cik, name, sic, sic_beschreibung, sektor_auto, waehrung, jetzt()),
    )
    con.commit()


def titel_alle(con) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT * FROM titel ORDER BY ticker")]


def titel(con, ticker) -> dict | None:
    r = con.execute("SELECT * FROM titel WHERE ticker = ?", (ticker,)).fetchone()
    return dict(r) if r else None


def titel_loeschen(con, ticker) -> None:
    con.execute("DELETE FROM titel WHERE ticker = ?", (ticker,))
    con.commit()


def sektor_manuell_setzen(con, ticker, sektor: str | None) -> None:
    con.execute("UPDATE titel SET sektor_manuell = ? WHERE ticker = ?", (sektor, ticker))
    con.commit()


def sektor(t: dict) -> str:
    """Manuelle Wahl hat Vorrang vor der automatischen Zuordnung."""
    return t.get("sektor_manuell") or t.get("sektor_auto") or "unbekannt"


# ---------------------------------------------------------------- Analysen

def analyse_speichern(con, ticker, waehrung, ergebnisse, kategorie_von, punkte_von, hinweise) -> int:
    cur = con.execute("INSERT INTO analysen (ticker, zeitpunkt, waehrung, hinweise) VALUES (?, ?, ?, ?)",
                      (ticker, jetzt(), waehrung, json.dumps(hinweise, ensure_ascii=False)))
    analyse_id = cur.lastrowid
    con.executemany(
        """INSERT INTO kennzahlen (analyse_id, schluessel, kategorie, rohwert, fixpunkte, punkte_damals,
                                   quelle, datenstand, grund, details, hinweis)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(analyse_id, e.schluessel, kategorie_von(e.schluessel), e.rohwert, e.fixpunkte, punkte_von(e),
          e.quelle, e.datenstand, e.grund, e.details, e.hinweis) for e in ergebnisse],
    )
    con.commit()
    return analyse_id


def analysen_fuer(con, ticker) -> list[dict]:
    rows = con.execute("SELECT * FROM analysen WHERE ticker = ? ORDER BY zeitpunkt, id", (ticker,))
    return [dict(r) for r in rows]


def letzte_analyse_ids(con) -> dict[str, int]:
    rows = con.execute("SELECT ticker, MAX(id) AS id FROM analysen GROUP BY ticker")
    return {r["ticker"]: r["id"] for r in rows}


def kennzahlen_fuer(con, analyse_ids: list[int]) -> list[dict]:
    if not analyse_ids:
        return []
    platz = ",".join("?" * len(analyse_ids))
    rows = con.execute(f"SELECT * FROM kennzahlen WHERE analyse_id IN ({platz}) ORDER BY id", analyse_ids)
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- Einschätzung

def einschaetzung_speichern(con, ticker, f1, f2, f3, f4, begruendung, gegenthese) -> None:
    if not begruendung or not begruendung.strip():
        raise ValueError("Die Begründung ist ein Pflichtfeld.")
    if not gegenthese or not gegenthese.strip():
        raise ValueError("Das Feld 'Ich liege falsch, wenn …' ist ein Pflichtfeld.")
    con.execute("INSERT INTO einschaetzungen (ticker, zeitpunkt, f1, f2, f3, f4, begruendung, gegenthese) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (ticker, jetzt(), f1, f2, f3, f4, begruendung.strip(), gegenthese.strip()))
    con.commit()


def einschaetzungen_fuer(con, ticker) -> list[dict]:
    rows = con.execute("SELECT * FROM einschaetzungen WHERE ticker = ? ORDER BY zeitpunkt, id", (ticker,))
    return [dict(r) for r in rows]


def einschaetzungen_alle(con) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT * FROM einschaetzungen ORDER BY zeitpunkt, id")]


# ---------------------------------------------------------------- Einstellungen

def einstellung(con, schluessel, standard=None):
    r = con.execute("SELECT wert FROM einstellungen WHERE schluessel = ?", (schluessel,)).fetchone()
    return json.loads(r["wert"]) if r else standard


def einstellung_setzen(con, schluessel, wert) -> None:
    con.execute("INSERT INTO einstellungen (schluessel, wert) VALUES (?, ?) "
                "ON CONFLICT(schluessel) DO UPDATE SET wert = excluded.wert",
                (schluessel, json.dumps(wert)))
    con.commit()
