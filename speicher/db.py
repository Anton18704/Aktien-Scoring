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
    hinweise    TEXT,
    dcf         TEXT
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
CREATE TABLE IF NOT EXISTS dcf_manuell (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT NOT NULL REFERENCES titel(ticker) ON DELETE CASCADE,
    zeitpunkt   TEXT NOT NULL,
    bear REAL, base REAL, bull REAL,
    start_fcf   REAL,
    notiz       TEXT
);
CREATE TABLE IF NOT EXISTS sektor_verlauf (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    zeitpunkt   TEXT NOT NULL,
    monat       TEXT NOT NULL,          -- JJJJ-MM
    sektor      TEXT NOT NULL,
    faktor REAL, grundfaktor REAL, bonus REAL,
    phase       TEXT,
    phase_roh   TEXT,                   -- berechnete Phase vor der Bestätigungsregel
    niveau REAL, richtung REAL,
    quelle      TEXT NOT NULL           -- "live" oder "rekonstruiert"
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
    for tabelle, spalte, typ in (("einschaetzungen", "gegenthese", "TEXT"), ("analysen", "dcf", "TEXT"),
                                 ("dcf_manuell", "start_fcf", "REAL"), ("sektor_verlauf", "phase_roh", "TEXT")):
        spalten = {r["name"] for r in con.execute(f"PRAGMA table_info({tabelle})")}
        if spalte not in spalten:
            con.execute(f"ALTER TABLE {tabelle} ADD COLUMN {spalte} {typ}")
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

def analyse_speichern(con, ticker, waehrung, ergebnisse, kategorie_von, punkte_von, hinweise, dcf=None) -> int:
    cur = con.execute("INSERT INTO analysen (ticker, zeitpunkt, waehrung, hinweise, dcf) VALUES (?, ?, ?, ?, ?)",
                      (ticker, jetzt(), waehrung, json.dumps(hinweise, ensure_ascii=False),
                       json.dumps(dcf, ensure_ascii=False) if dcf is not None else None))
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


# ---------------------------------------------------------------- DCF: manuelles Wachstum

MANUELL_FELDER = ("bear", "base", "bull", "start_fcf")


def dcf_manuell_speichern(con, ticker, bear, base, bull, notiz="", start_fcf=None) -> None:
    """Neuer Eintrag (der letzte gilt). Alles None = zurück auf automatisch."""
    con.execute("INSERT INTO dcf_manuell (ticker, zeitpunkt, bear, base, bull, start_fcf, notiz) VALUES (?,?,?,?,?,?,?)",
                (ticker, jetzt(), bear, base, bull, start_fcf, (notiz or "").strip()))
    con.commit()


def _manuell_zahlen(r) -> dict:
    """Zahlenfelder sicher als float (ältere Datenbanken können sie als Text gespeichert haben)."""
    d = dict(r)
    for k in MANUELL_FELDER:
        if d.get(k) is not None:
            d[k] = float(d[k])
    return d


def dcf_manuell(con, ticker) -> dict | None:
    r = con.execute("SELECT * FROM dcf_manuell WHERE ticker = ? ORDER BY zeitpunkt DESC, id DESC LIMIT 1",
                    (ticker,)).fetchone()
    if r is None or all(r[k] is None for k in MANUELL_FELDER):
        return None
    return _manuell_zahlen(r)


def dcf_manuell_alle(con) -> dict[str, dict]:
    ergebnis = {}
    for r in con.execute("SELECT * FROM dcf_manuell ORDER BY zeitpunkt, id"):
        ergebnis[r["ticker"]] = _manuell_zahlen(r)
    return {t: r for t, r in ergebnis.items() if any(r[k] is not None for k in MANUELL_FELDER)}


# ---------------------------------------------------------------- Sektor-Verlauf

_VERLAUF_FELDER = ("monat", "sektor", "faktor", "grundfaktor", "bonus", "phase", "phase_roh", "niveau", "richtung",
                   "quelle")


def sektor_verlauf_speichern(con, zeilen: list[dict]) -> None:
    con.executemany(f"INSERT INTO sektor_verlauf (zeitpunkt, {', '.join(_VERLAUF_FELDER)}) "
                    f"VALUES (?, {', '.join('?' * len(_VERLAUF_FELDER))})",
                    [(jetzt(), *(z.get(f) for f in _VERLAUF_FELDER)) for z in zeilen])
    con.commit()


def sektor_verlauf_ersetzen_rekonstruiert(con, zeilen: list[dict]) -> None:
    """Rückrechnung neu speichern (nur abgeleitete Daten – Live-Einträge bleiben unberührt)."""
    con.execute("DELETE FROM sektor_verlauf WHERE quelle = 'rekonstruiert'")
    sektor_verlauf_speichern(con, zeilen)


def sektor_verlauf(con) -> list[dict]:
    """Ein Eintrag pro Monat und Sektor: Live-Werte haben Vorrang, sonst die Rückrechnung; je Monat der neueste."""
    rows = [dict(r) for r in con.execute("SELECT * FROM sektor_verlauf ORDER BY zeitpunkt, id")]
    beste: dict[tuple, dict] = {}
    for r in rows:
        schluessel = (r["monat"], r["sektor"])
        bisher = beste.get(schluessel)
        if bisher is None or r["quelle"] == "live" or bisher["quelle"] != "live":
            beste[schluessel] = r
    return sorted(beste.values(), key=lambda r: (r["monat"], r["sektor"]))


# ---------------------------------------------------------------- Einstellungen

def einstellung(con, schluessel, standard=None):
    r = con.execute("SELECT wert FROM einstellungen WHERE schluessel = ?", (schluessel,)).fetchone()
    return json.loads(r["wert"]) if r else standard


def einstellung_setzen(con, schluessel, wert) -> None:
    con.execute("INSERT INTO einstellungen (schluessel, wert) VALUES (?, ?) "
                "ON CONFLICT(schluessel) DO UPDATE SET wert = excluded.wert",
                (schluessel, json.dumps(wert)))
    con.commit()
