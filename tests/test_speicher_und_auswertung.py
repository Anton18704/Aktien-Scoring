"""Zusammenspiel: Speichern, Verlauf, Einschätzung, Gewichte."""
import pytest

import auswertung
from kern.kennzahlen import Ergebnis
from kern.konfig import lade_schwellen, sektor_fuer_sic
from speicher import db


@pytest.fixture
def con(tmp_path):
    return db.verbinden(tmp_path / "test.db")


def _speichern(con, rohwert_fcf=7.0):
    s = lade_schwellen()
    ergebnisse = [Ergebnis(k, rohwert=kz["zehn"]) for k, kz in s["kennzahlen"].items()]
    ergebnisse[0].rohwert = rohwert_fcf
    return db.analyse_speichern(con, "TEST", "USD", ergebnisse,
                                lambda k: s["kennzahlen"][k]["kategorie"], lambda e: None, [])


def test_sektoren():
    assert sektor_fuer_sic("3571") == "IT"            # Apple
    assert sektor_fuer_sic(2080) == "Basiskonsum"     # Coca-Cola
    assert sektor_fuer_sic(3531) == "Industrie"       # Caterpillar
    assert sektor_fuer_sic(6798) == "Immobilien"      # REIT
    assert sektor_fuer_sic(6021) == "Finanzwerte"     # Bank
    assert sektor_fuer_sic(2834) == "Gesundheit"      # Pharma
    assert sektor_fuer_sic(None) is None


def test_erneute_analyse_legt_neuen_eintrag_an(con):
    db.titel_speichern(con, "TEST", 1, "Test Inc", "3571", "", "IT", "USD")
    _speichern(con, 7.0)
    _speichern(con, 4.0)
    assert len(db.analysen_fuer(con, "TEST")) == 2
    v = auswertung.verlauf(con, "TEST")
    assert len(v) == 2
    assert v["A"].iloc[0] == pytest.approx(10)
    assert v["A"].iloc[1] == pytest.approx(50 / 6)     # A hat 6 Kennzahlen: FCF-Rendite 0 Punkte, Rest 10


def test_einschaetzung_offen_und_danach(con):
    db.titel_speichern(con, "TEST", 1, "Test Inc", "3571", "", "IT", "USD")
    _speichern(con)
    df = auswertung.uebersicht(con)
    assert "Einschätzung offen" in df.loc[0, "Hinweis"]
    assert df.loc[0, "Gesamtscore"] == pytest.approx(100)
    db.einschaetzung_speichern(con, "TEST", 0, 0, 0, 0, "Verstehe ich nicht.", "immer")
    df = auswertung.uebersicht(con)
    assert "Einschätzung offen" not in df.loc[0, "Hinweis"]
    assert "K.o.: E" in df.loc[0, "Hinweis"]               # E mit 0 Punkten liegt unter der K.o.-Schwelle
    assert df.loc[0, "Gesamtscore"] == pytest.approx(80)  # E (20 %) mit 0 Punkten


def test_begruendung_pflicht(con):
    db.titel_speichern(con, "TEST", 1, "Test Inc", "3571", "", "IT", "USD")
    with pytest.raises(ValueError):
        db.einschaetzung_speichern(con, "TEST", 5, 5, 5, 5, "  ", "Gegenthese")
    with pytest.raises(ValueError):
        db.einschaetzung_speichern(con, "TEST", 5, 5, 5, 5, "Begründung", " ")


def test_gewichte_wirken_sofort(con):
    db.titel_speichern(con, "TEST", 1, "Test Inc", "3571", "", "IT", "USD")
    _speichern(con, 4.0)
    db.einschaetzung_speichern(con, "TEST", 10, 10, 10, 10, "ok", "Marge sinkt")
    vorher = auswertung.uebersicht(con).loc[0, "Gesamtscore"]
    db.einstellung_setzen(con, "gewichte", {"A": 100, "B": 0, "C": 0, "D": 0, "E": 0})
    nachher = auswertung.uebersicht(con).loc[0, "Gesamtscore"]
    assert nachher == pytest.approx(500 / 6, abs=0.05) and nachher != vorher


def test_manueller_sektor_hat_vorrang(con):
    db.titel_speichern(con, "TEST", 1, "Test Inc", "3571", "", "IT", "USD")
    db.sektor_manuell_setzen(con, "TEST", "Kommunikation")
    assert db.sektor(db.titel(con, "TEST")) == "Kommunikation"
    db.titel_speichern(con, "TEST", 1, "Test Inc", "3571", "", "IT", "USD")   # erneute Analyse
    assert db.sektor(db.titel(con, "TEST")) == "Kommunikation"


def test_loeschen_entfernt_alles(con):
    db.titel_speichern(con, "TEST", 1, "Test Inc", "3571", "", "IT", "USD")
    aid = _speichern(con)
    db.titel_loeschen(con, "TEST")
    assert db.kennzahlen_fuer(con, [aid]) == []


def test_alte_datenbank_wird_ergaenzt(tmp_path):
    """Eine Datenbank aus der ersten Version (ohne Spalte 'gegenthese') wird beim Öffnen ergänzt."""
    import sqlite3
    pfad = tmp_path / "alt.db"
    alt = sqlite3.connect(pfad)
    alt.executescript("""CREATE TABLE einschaetzungen (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL,
        zeitpunkt TEXT NOT NULL, f1 REAL, f2 REAL, f3 REAL, f4 REAL, begruendung TEXT NOT NULL);
        INSERT INTO einschaetzungen (ticker, zeitpunkt, f1, f2, f3, f4, begruendung)
        VALUES ('KO', '2026-01-01', 5, 5, 5, 5, 'alt');""")
    alt.commit()
    alt.close()
    con = db.verbinden(pfad)
    e = db.einschaetzungen_fuer(con, "KO")[0]
    assert e["begruendung"] == "alt" and e["gegenthese"] is None
