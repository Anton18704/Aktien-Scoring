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
    # Die DCF-Sicherheitsmarge wird nicht gespeichert, sondern live berechnet
    ergebnisse = [Ergebnis(k, rohwert=kz["zehn"]) for k, kz in s["kennzahlen"].items() if k != "dcf_sicherheitsmarge"]
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
    assert v["A"].iloc[1] == pytest.approx(40 / 5)     # A ohne DCF: FCF-Rendite 0 Punkte, 4 weitere je 10


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
    assert nachher == pytest.approx(80) and nachher != vorher


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


def test_dcf_wird_live_berechnet_und_manuell_ueberschreibbar(con):
    import json
    from kern.dcf import DcfEingaben
    db.titel_speichern(con, "TEST", 1, "Test Inc", "2080", "", "Basiskonsum", "USD")
    s = lade_schwellen()
    eingaben = DcfEingaben(fcf_ttm=100, fcf_jahre=[100, 100, 100], wachstum=5, aktien=100, kurs=10,
                           nettocash=0, zins=4.0)
    db.analyse_speichern(con, "TEST", "USD", [], lambda k: s["kennzahlen"][k]["kategorie"], lambda e: None, [],
                         dcf=eingaben.als_dict())
    analyse = db.analysen_fuer(con, "TEST")[-1]
    titel = db.titel(con, "TEST")
    from kern.konfig import lade_dcf
    erg, _ = auswertung.dcf_berechnen(analyse, titel, db.dcf_manuell(con, "TEST"), s, lade_dcf())
    assert erg.grund is None and erg.fairer_wert > 10        # FCF-Rendite 10 % → deutlich unterbewertet
    vorher = erg.fairer_wert
    db.dcf_manuell_speichern(con, "TEST", -5, 0, 2, "Sondereffekte")
    erg, _ = auswertung.dcf_berechnen(analyse, titel, db.dcf_manuell(con, "TEST"), s, lade_dcf())
    assert erg.manuell and erg.fairer_wert < vorher
    db.dcf_manuell_speichern(con, "TEST", None, None, None)  # zurück auf automatisch
    assert db.dcf_manuell(con, "TEST") is None
    auto, eing = auswertung.dcf_berechnen(analyse, titel, None, s, lade_dcf())
    zeile = auswertung.dcf_zeile(analyse, auto, eing)
    assert zeile["rohwert"] == pytest.approx(auto.sicherheitsmarge) and zeile["rohwert"] > 0
    assert zeile["kategorie"] == "A" and zeile["grund"] is None
    assert zeile["rohwert"] == pytest.approx(vorher_marge(vorher))


def vorher_marge(fairer_wert, kurs=10):
    return (fairer_wert - kurs) / fairer_wert * 100


def test_normalisierter_fcf_wird_gespeichert(con):
    db.titel_speichern(con, "TEST", 1, "Test Inc", "2080", "", "Basiskonsum", "USD")
    db.dcf_manuell_speichern(con, "TEST", None, None, None, "Sondereffekte 2025", start_fcf=11.5e9)
    m = db.dcf_manuell(con, "TEST")
    assert m["start_fcf"] == 11.5e9 and m["notiz"] == "Sondereffekte 2025"
    assert "TEST" in db.dcf_manuell_alle(con)
    db.dcf_manuell_speichern(con, "TEST", None, None, None, "zurückgesetzt")
    assert db.dcf_manuell(con, "TEST") is None


def test_dcf_manuell_aus_vorversion_wird_nachgeruestet(tmp_path):
    """dcf_manuell ohne Spalte start_fcf (Version vom DCF-Start) → Spalte wird als Zahl ergänzt."""
    import sqlite3
    pfad = tmp_path / "vorversion.db"
    alt = sqlite3.connect(pfad)
    alt.executescript("""CREATE TABLE titel (ticker TEXT PRIMARY KEY);
        CREATE TABLE dcf_manuell (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL, zeitpunkt TEXT NOT NULL,
            bear REAL, base REAL, bull REAL, notiz TEXT);
        INSERT INTO titel VALUES ('KO');""")
    alt.commit()
    alt.close()
    con = db.verbinden(pfad)
    db.dcf_manuell_speichern(con, "KO", 2, 5, 7, "Test", start_fcf=11.5e9)
    m = db.dcf_manuell(con, "KO")
    assert isinstance(m["start_fcf"], float) and m["start_fcf"] / 1e9 == pytest.approx(11.5)
    typ = {r[1]: r[2] for r in con.execute("PRAGMA table_info(dcf_manuell)")}["start_fcf"]
    assert typ == "REAL"
