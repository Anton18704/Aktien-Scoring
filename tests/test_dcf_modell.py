"""Tests für das eigene DCF-Modell (kern/dcf_modell.py) und seine Anbindung an Speicher und Score."""
import json
from dataclasses import replace

import pytest

import auswertung
from kern import dcf_modell as m
from kern.kennzahlen import modell_basis
from speicher import db


def basis(**kw):
    werte = dict(umsatz=1000.0, ebit=200.0, abschreibungen=50.0, capex=60.0, nwc=100.0, steuersatz=20.0,
                 schulden=300.0, cash=100.0, zinsaufwand=15.0, aktien=10.0, kurs=100.0,
                 historie=[{"jahr": 2020 + i, "umsatz": u, "ebit": u * 0.2, "abschreibungen": u * 0.05,
                            "capex": u * 0.06} for i, u in enumerate([800, 850, 900, 950, 1000])])
    werte.update(kw)
    return m.ModellBasis(**werte)


def annahmen(**kw):
    werte = dict(wachstum=[5.0] * 5, ebit_marge=[20.0] * 5, steuersatz=20.0, abschr_quote=5.0, capex_quote=6.0,
                 nwc_quote=10.0, wacc_manuell=9.0, g_ewig=2.0, exit_multiple=10.0, endwert_methode="gordon")
    werte.update(kw)
    return m.Annahmen(**werte)


def test_free_cashflow_rechnung_jahr_1():
    erg = m.rechnen(annahmen(), basis())
    z = erg.zeilen[0]
    assert z["umsatz"] == pytest.approx(1050)
    assert z["ebit"] == pytest.approx(210)
    assert z["nopat"] == pytest.approx(168)                      # 210 – 20 % Steuern
    assert z["delta_nwc"] == pytest.approx(5)                    # 10 % von 50 Mehrumsatz
    assert z["fcf"] == pytest.approx(168 + 52.5 - 63 - 5)
    assert z["diskontfaktor"] == pytest.approx(1 / 1.09)
    assert z["barwert"] == pytest.approx(z["fcf"] / 1.09)


def test_ohne_wachstum_und_reinvestition_ist_es_eine_ewige_rente():
    """Kein Wachstum, Capex = Abschreibungen → Wert = NOPAT ÷ WACC (klassische Rentenformel)."""
    a = annahmen(wachstum=[0.0] * 10, ebit_marge=[20.0] * 10, capex_quote=5.0, g_ewig=0.0)
    erg = m.rechnen(a, basis())
    assert erg.unternehmenswert == pytest.approx(160 / 0.09)
    assert erg.eigenkapitalwert == pytest.approx(160 / 0.09 - 200)
    assert erg.fairer_wert == pytest.approx((160 / 0.09 - 200) / 10)


def test_endwert_methoden_und_gegenprobe():
    b = basis()
    gordon = m.rechnen(annahmen(endwert_methode="gordon"), b)
    multiple = m.rechnen(annahmen(endwert_methode="multiple"), b)
    mittel = m.rechnen(annahmen(endwert_methode="durchschnitt"), b)
    assert mittel.endwert == pytest.approx((gordon.endwert + multiple.endwert) / 2)
    assert multiple.endwert == pytest.approx(multiple.ebitda_letztes * 10)
    # Gegenprobe: das Multiple, das der Gordon-Endwert bedeutet, ergibt wieder denselben Endwert
    probe = m.rechnen(annahmen(endwert_methode="multiple", exit_multiple=gordon.impl_multiple), b)
    assert probe.endwert == pytest.approx(gordon.endwert)
    # … und das ewige Wachstum, das der Multiple-Endwert bedeutet, ebenso
    probe = m.rechnen(annahmen(endwert_methode="gordon", g_ewig=multiple.impl_wachstum), b)
    assert probe.endwert == pytest.approx(multiple.endwert)


def test_gordon_instabil_faellt_auf_multiple_zurueck():
    erg = m.rechnen(annahmen(wacc_manuell=3.0, g_ewig=2.5, endwert_methode="gordon"), basis())
    assert erg.endwert_gordon is None and erg.endwert == pytest.approx(erg.endwert_multiple)
    assert any("nicht berechenbar" in h for h in erg.hinweise)


def test_mitte_jahr_erhoeht_den_wert():
    b = basis()
    assert m.rechnen(annahmen(mitte_jahr=True), b).fairer_wert > m.rechnen(annahmen(), b).fairer_wert
    assert m.rechnen(annahmen(mitte_jahr=True), b).zeilen[0]["zeit"] == 0.5


def test_wacc_aus_kapitalkosten():
    a = annahmen(wacc_manuell=None, rf=4.0, beta=1.2, erp=5.0, fk_zins=6.0, fk_anteil=20.0, steuersatz=25.0)
    assert a.ek_kosten == pytest.approx(10.0)
    assert a.wacc == pytest.approx(0.8 * 10.0 + 0.2 * 6.0 * 0.75)


def test_manuelle_nettoschulden_und_startumsatz():
    b = basis()
    normal = m.rechnen(annahmen(), b)
    assert m.rechnen(annahmen(nettoschulden=0.0), b).fairer_wert == pytest.approx(normal.fairer_wert + 20)
    assert m.rechnen(annahmen(umsatz_start=2000.0), b).zeilen[0]["umsatz"] == pytest.approx(2100)


def test_empfindlichkeit_mitte_entspricht_annahmen():
    a, b = annahmen(endwert_methode="durchschnitt"), basis()
    fair = m.rechnen(a, b).fairer_wert
    for art in ("wachstum", "multiple"):
        emp = m.empfindlichkeit(a, b, art)
        assert emp["werte"][2][2] == pytest.approx(fair)
        assert emp["werte"][0][2] > emp["werte"][4][2]           # höherer Zins → niedrigerer Wert


def test_vorschlag_aus_der_vergangenheit():
    b = basis()
    v = m.vorschlag(b, wachstum_start=6.0, rf=4.0, beta=1.1, erp=5.0, g_ewig=2.5, exit_multiple=11.0)
    assert v.jahre == 10 and v.wachstum[:5] == [6.0] * 5 and v.wachstum[-1] == pytest.approx(2.5)
    assert v.ebit_marge == [20.0] * 10
    assert v.capex_quote == pytest.approx(6.0) and v.abschr_quote == pytest.approx(5.0)
    assert v.nwc_quote == pytest.approx(10.0)
    assert v.fk_zins == pytest.approx(5.0)                         # 15 ÷ 300
    assert v.fk_anteil == pytest.approx(300 / 1300 * 100, abs=0.05)


def test_linear():
    assert m.linear(10, 2, 5) == [10, 8, 6, 4, 2]


def test_ohne_daten_kein_ergebnis():
    assert m.rechnen(annahmen(), basis(grund="Umsatz nicht gefunden")).grund == "Umsatz nicht gefunden"
    assert m.rechnen(annahmen(), basis(aktien=None)).grund
    assert m.rechnen(annahmen(wachstum=[5.0], ebit_marge=[1.0, 2.0]), basis()).grund


def test_als_dict_rundreise():
    a = annahmen(mitte_jahr=True, nettoschulden=5.0)
    assert m.Annahmen.aus_dict(json.loads(json.dumps(a.als_dict()))) == a
    b = basis()
    assert m.ModellBasis.aus_dict(json.loads(json.dumps(b.als_dict()))) == b


def test_modell_basis_aus_finanzdaten(fd_basis):
    b = modell_basis(fd_basis)
    assert b.grund is None
    assert b.umsatz == 1000 and b.ebit == 200 and b.capex == 30
    assert b.schulden == pytest.approx(475) and b.cash == pytest.approx(150)
    # Working Capital = Umlaufvermögen 600 – Cash 150 – (kurzfr. Verbindlichkeiten 400 – kurzfr. Schulden 75)
    assert b.nwc == pytest.approx(125)
    assert b.aktien == 100 and b.kurs == 20


def test_eigenes_modell_ersetzt_automatisches_dcf_im_score(tmp_path):
    con = db.verbinden(tmp_path / "t.db")
    db.titel_speichern(con, "TEST", 1, "Test AG", "2000", "", "Basiskonsum", "USD")
    b = basis()
    aid = db.analyse_speichern(con, "TEST", "USD", [], lambda s: "A", lambda e: None, [], dcf=None,
                               modell=b.als_dict())
    analyse = db.analysen_fuer(con, "TEST")[0]
    assert analyse["id"] == aid
    a = annahmen()
    db.dcf_modell_speichern(con, "TEST", a.als_dict(), im_score=True, notiz="Test")
    gespeichert = db.dcf_modell(con, "TEST")
    assert gespeichert["im_score"] and gespeichert["annahmen"] == a.als_dict()

    zeilen = auswertung.mit_dcf([], analyse, db.titel(con, "TEST"), None, {"optionen": {}}, {}, gespeichert)
    zeile = zeilen[-1]
    assert zeile["schluessel"] == "dcf_sicherheitsmarge"
    assert zeile["rohwert"] == pytest.approx(m.rechnen(a, b).sicherheitsmarge)
    assert zeile["hinweis"].startswith("eigenes DCF-Modell")

    # Nicht für den Score → automatisches DCF (hier ohne DCF-Daten: Hinweis „bitte neu analysieren“)
    db.dcf_modell_speichern(con, "TEST", a.als_dict(), im_score=False)
    zeile = auswertung.mit_dcf([], analyse, db.titel(con, "TEST"), None, {"optionen": {}}, {},
                               db.dcf_modell(con, "TEST"))[-1]
    assert zeile["rohwert"] is None and "neu analysieren" in zeile["grund"]

    # Verwerfen → kein Modell mehr
    db.dcf_modell_speichern(con, "TEST", None)
    assert db.dcf_modell(con, "TEST") is None and db.dcf_modelle_alle(con) == {}


def test_empfindlichkeit_aendert_annahmen_nicht():
    a = annahmen()
    kopie = replace(a)
    m.empfindlichkeit(a, basis())
    assert a == kopie
