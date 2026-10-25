from datetime import date

import pandas as pd
import pytest

from kern import kennzahlen as k
from tests.conftest import jahresreihe, w


# ------------------------------------------------------------ Hilfen

def test_finanzschulden_ohne_doppelzaehlung(fd_basis):
    s, _ = k.finanzschulden(fd_basis, date(2025, 12, 31))
    assert s == 400 + 50 + 25

    # DebtCurrent enthält bereits alles Kurzfristige
    fd_basis.bilanz["schulden_kurzfristig_gesamt"] = [w(90, "2025-12-31")]
    s, _ = k.finanzschulden(fd_basis, date(2025, 12, 31))
    assert s == 400 + 90

    # nur LongTermDebt (inkl. kurzfristigem Teil) vorhanden
    fd_basis.bilanz = {"ltd_gesamt": [w(500, "2025-12-31")], "ltd_kurzfristig": [w(50, "2025-12-31")]}
    s, _ = k.finanzschulden(fd_basis, date(2025, 12, 31))
    assert s == 500


def test_keine_schulden_ausgewiesen(fd_leer):
    s, quelle = k.finanzschulden(fd_leer, date(2025, 12, 31))
    assert s == 0 and "keine" in quelle


def test_marktkap_bei_fremder_kurswaehrung(fd_basis):
    fd_basis.waehrung = "EUR"
    mk, grund, _ = k.marktkapitalisierung(fd_basis)
    assert mk is None and "Währungsumrechnung" in grund


# ------------------------------------------------------------ A

def test_fcf_rendite(fd_basis):
    e = k.fcf_rendite(fd_basis)
    assert e.rohwert == pytest.approx(150 / 2000 * 100)
    assert e.datenstand == "2025-12-31"
    assert e.grund is None


def test_fcf_rendite_ohne_capex(fd_basis):
    del fd_basis.ttm["capex"]
    e = k.fcf_rendite(fd_basis)
    assert e.rohwert is None and "Capex" in e.grund


def test_ausschuettungsrendite(fd_basis):
    e = k.ausschuettungsrendite(fd_basis)
    assert e.rohwert == pytest.approx((40 + 30 - 10) / 2000 * 100)


def test_ausschuettungsrendite_fehlende_posten_zaehlen_null(fd_basis):
    del fd_basis.ttm["dividenden"], fd_basis.ttm["aktienausgabe"]
    e = k.ausschuettungsrendite(fd_basis)
    assert e.rohwert == pytest.approx(30 / 2000 * 100)
    assert "Dividenden" in e.hinweis


def _ev_historie(fd):
    """10 Geschäftsjahre mit EV/EBIT jeweils 10 (Kurs 10, 100 Aktien, keine Schulden, Cash 0)."""
    jahre = [date(2015 + i, 12, 31) for i in range(10)]
    fd.jahre["ebit"] = [w(100, d) for d in jahre]
    fd.jahre["aktien_verwaessert"] = [w(100, d) for d in jahre]
    fd.bilanz["cash"] = [w(0, d) for d in jahre] + fd.bilanz["cash"]
    tage = pd.bdate_range("2015-01-01", "2025-12-31")
    fd.kurse = pd.Series(10.0, index=tage)


def test_ev_ebit_historie(fd_basis):
    _ev_historie(fd_basis)
    e = k.ev_ebit_historie(fd_basis)
    aktuell = (2000 + 475 - 150) / 200
    assert e.rohwert == pytest.approx((aktuell / 10 - 1) * 100)


def test_ev_ebit_historie_zu_kurz(fd_basis):
    _ev_historie(fd_basis)
    fd_basis.jahre["ebit"] = fd_basis.jahre["ebit"][-3:]
    e = k.ev_ebit_historie(fd_basis)
    assert e.rohwert is None and "mindestens 5" in e.grund


def test_ev_ebit_negativ(fd_basis):
    fd_basis.ttm["ebit"] = w(-5, "2025-12-31")
    assert "negativ" in k.ev_ebit_historie(fd_basis).grund


def test_max_kursrueckgang():
    fd = k.Finanzdaten()
    tage = pd.bdate_range("2020-11-01", "2025-12-31")
    werte = pd.Series(100.0, index=tage)
    werte.loc["2022-01-01":"2022-06-30"] = 150.0
    werte.loc["2022-07-01":"2023-01-31"] = 60.0      # Rückgang 150 -> 60 = 60 %
    fd.kurse = werte
    e = k.max_kursrueckgang(fd)
    assert e.rohwert == pytest.approx(60.0)


def test_max_kursrueckgang_zu_kurz():
    fd = k.Finanzdaten()
    fd.kurse = pd.Series(100.0, index=pd.bdate_range("2024-01-01", "2025-12-31"))
    assert "kürzer" in k.max_kursrueckgang(fd).grund


# ------------------------------------------------------------ B

def test_umsatz_cagr():
    fd = k.Finanzdaten()
    fd.jahre["umsatz"] = jahresreihe([100 * 1.08 ** i for i in range(11)])
    e = k.umsatz_cagr(fd)
    assert e.rohwert == pytest.approx(8.0)


def test_umsatz_cagr_ohne_altdaten():
    fd = k.Finanzdaten()
    fd.jahre["umsatz"] = jahresreihe([100, 110, 120])
    assert "vor 5 Jahren" in k.umsatz_cagr(fd).grund


def test_fcf_je_aktie_cagr():
    fd = k.Finanzdaten()
    fd.jahre["ocf"] = jahresreihe([110, 0, 0, 0, 0, 230])
    fd.jahre["capex"] = jahresreihe([10, 0, 0, 0, 0, 30])
    fd.jahre["aktien_verwaessert"] = jahresreihe([100, 0, 0, 0, 0, 80])
    e = k.fcf_je_aktie_cagr(fd)
    # FCF/Aktie 1,00 -> 2,50 in 5 Jahren
    assert e.rohwert == pytest.approx((2.5 ** (1 / 5) - 1) * 100)


def test_fcf_je_aktie_negativ():
    fd = k.Finanzdaten()
    fd.jahre["ocf"] = jahresreihe([10, 0, 0, 0, 0, 230])
    fd.jahre["capex"] = jahresreihe([20, 0, 0, 0, 0, 30])
    fd.jahre["aktien_verwaessert"] = jahresreihe([100] * 6)
    assert "nicht positiv" in k.fcf_je_aktie_cagr(fd).grund


def test_bestaendigkeit():
    fd = k.Finanzdaten()
    # 11 Jahre -> 10 Vergleiche, 7 davon mit Plus
    fd.jahre["umsatz"] = jahresreihe([100, 110, 120, 115, 125, 130, 128, 140, 150, 145, 160])
    e = k.umsatz_bestaendigkeit(fd)
    assert e.rohwert == 7


def test_bestaendigkeit_hochgerechnet():
    fd = k.Finanzdaten()
    fd.jahre["umsatz"] = jahresreihe([100, 110, 120, 130, 125, 140])   # 4 von 5
    e = k.umsatz_bestaendigkeit(fd)
    assert e.rohwert == pytest.approx(8.0)
    assert "hochgerechnet" in e.hinweis


# ------------------------------------------------------------ C

def test_roic():
    fd = k.Finanzdaten()
    jahre = [date(2021 + i, 12, 31) for i in range(5)]
    fd.jahre["ebit"] = [w(100, d) for d in jahre]
    fd.jahre["steuern"] = [w(20, d) for d in jahre]
    fd.jahre["vorsteuergewinn"] = [w(100, d) for d in jahre]
    fd.bilanz["eigenkapital"] = [w(500, d) for d in jahre]
    fd.bilanz["ltd_langfristig"] = [w(200, d) for d in jahre]
    fd.bilanz["cash"] = [w(100, d) for d in jahre]
    e = k.roic(fd)
    assert e.rohwert == pytest.approx(100 * 0.8 / 600 * 100)


def test_steuersatz_begrenzt():
    fd = k.Finanzdaten()
    d = date(2025, 12, 31)
    fd.jahre["steuern"], fd.jahre["vorsteuergewinn"] = [w(60, d)], [w(100, d)]
    assert k.steuersatz(fd, d) == 0.35
    fd.jahre["vorsteuergewinn"] = [w(-10, d)]
    assert k.steuersatz(fd, d) == 0.21


def test_bruttomarge_stabilitaet():
    fd = k.Finanzdaten()
    fd.jahre["umsatz"] = jahresreihe([100] * 6)
    fd.jahre["bruttogewinn"] = jahresreihe([40, 42, 38, 40, 44, 36])
    e = k.bruttomarge_stabilitaet(fd)
    import statistics
    assert e.rohwert == pytest.approx(statistics.stdev([40, 42, 38, 40, 44, 36]))


def test_bruttomarge_aus_herstellkosten():
    fd = k.Finanzdaten()
    fd.jahre["umsatz"] = jahresreihe([100] * 5)
    fd.jahre["herstellkosten"] = jahresreihe([60] * 5)
    assert k.bruttomarge_stabilitaet(fd).rohwert == pytest.approx(0)


def test_fcf_umwandlung():
    fd = k.Finanzdaten()
    fd.jahre["ocf"] = jahresreihe([100] * 5)
    fd.jahre["capex"] = jahresreihe([20] * 5)
    fd.jahre["nettogewinn"] = jahresreihe([100] * 5)
    assert k.fcf_umwandlung(fd).rohwert == pytest.approx(80)


def test_fcf_umwandlung_verlust():
    fd = k.Finanzdaten()
    fd.jahre["ocf"] = jahresreihe([100] * 5)
    fd.jahre["capex"] = jahresreihe([20] * 5)
    fd.jahre["nettogewinn"] = jahresreihe([-100] * 5)
    assert "nicht positiv" in k.fcf_umwandlung(fd).grund


# ------------------------------------------------------------ D

def test_nettoverschuldung_ebitda(fd_basis):
    e = k.nettoverschuldung_ebitda(fd_basis)
    assert e.rohwert == pytest.approx((475 - 150) / 250)
    assert e.fixpunkte is None


def test_nettocash_gibt_zehn(fd_basis):
    fd_basis.bilanz["cash"] = [w(1000, "2025-12-31")]
    e = k.nettoverschuldung_ebitda(fd_basis)
    assert e.fixpunkte == 10


def test_negatives_ebitda_wird_ausgelassen(fd_basis):
    fd_basis.ttm["ebit"] = w(-300, "2025-12-31")
    e = k.nettoverschuldung_ebitda(fd_basis)
    assert e.rohwert is None and "negativ" in e.grund


def test_zinsdeckung(fd_basis):
    assert k.zinsdeckung(fd_basis).rohwert == pytest.approx(10)


def test_entschuldungsdauer(fd_basis):
    # Nettoschulden 475 – 150 = 325, FCF 180 – 30 = 150
    e = k.entschuldungsdauer(fd_basis)
    assert e.rohwert == pytest.approx(325 / 150)


def test_entschuldungsdauer_nettocash(fd_basis):
    fd_basis.bilanz["cash"] = [w(1000, "2025-12-31")]
    assert k.entschuldungsdauer(fd_basis).fixpunkte == 10


def test_entschuldungsdauer_negativer_fcf(fd_basis):
    fd_basis.ttm["capex"] = w(500, "2025-12-31")
    e = k.entschuldungsdauer(fd_basis)
    assert e.fixpunkte == 0 and "negativer Free Cashflow" in e.hinweis


def test_altman_z(fd_basis):
    erwartet = 1.2 * 0.1 + 1.4 * 0.25 + 3.3 * 0.1 + 0.6 * (2000 / 1200) + 1.0 * 0.5
    assert k.altman_z(fd_basis).rohwert == pytest.approx(erwartet)


def test_altman_ohne_gewinnruecklagen(fd_basis):
    del fd_basis.bilanz["gewinnruecklagen"]
    assert "Gewinnrücklagen" in k.altman_z(fd_basis).grund


def test_alle_berechnen_passt_zur_konfiguration(fd_basis):
    ergebnisse = k.alle_berechnen(fd_basis)
    alle = set(__import__("kern.konfig", fromlist=["x"]).lade_schwellen()["kennzahlen"])
    assert {e.schluessel for e in ergebnisse} == alle - {"dcf_sicherheitsmarge"}   # DCF wird live berechnet


# ------------------------------------------------------------ Korrekturen nach dem Echtdaten-Test

def test_schulden_nur_im_jahresbericht(fd_basis):
    """Wie bei Caterpillar: Schulden zum Quartalsstichtag fehlen, im letzten 10-K vorhanden."""
    fd_basis.bilanz = {k: v for k, v in fd_basis.bilanz.items()
                       if k not in ("ltd_langfristig", "ltd_kurzfristig", "commercial_paper")}
    fd_basis.bilanz["ltd_langfristig"] = [w(300, "2025-06-30")]
    fd_basis.bilanz["kurzfr_kredite"] = [w(50, "2025-06-30")]
    s, quelle = k.finanzschulden(fd_basis, date(2025, 12, 31))
    assert s == 350
    assert "Schulden zum 30.06.2025" in quelle


def test_schulden_zu_alt_werden_nicht_verwendet(fd_basis):
    fd_basis.bilanz = {"ltd_langfristig": [w(300, "2023-12-31")]}
    s, _ = k.finanzschulden(fd_basis, date(2025, 12, 31))
    assert s == 0


def test_tilgungen_12_monate_als_ersatz():
    fd = k.Finanzdaten()
    fd.bilanz = {"ltd_langfristig": [w(300, "2025-12-31")], "ltd_faellig_12m": [w(70, "2025-12-31")]}
    s, quelle = k.finanzschulden(fd, date(2025, 12, 31))
    assert s == 370 and "Tilgungen" in quelle


def test_zinsdeckung_ohne_zinsaufwand_aber_mit_schulden(fd_basis):
    del fd_basis.ttm["zinsaufwand"]
    e = k.zinsdeckung(fd_basis)
    assert e.fixpunkte is None and e.rohwert is None
    assert "nicht (mehr) separat" in e.grund


def test_zinsdeckung_schuldenfrei_gibt_zehn(fd_basis):
    del fd_basis.ttm["zinsaufwand"]
    for kz in ("ltd_langfristig", "ltd_kurzfristig", "commercial_paper"):
        del fd_basis.bilanz[kz]
    assert k.zinsdeckung(fd_basis).fixpunkte == 10



# ------------------------------------------------------------ Verbesserungen aus der Analysten-Durchsicht

def test_fcf_abzug_aktienverguetung(fd_basis):
    fd_basis.ttm["aktienverguetung"] = w(50, "2025-12-31")
    assert k.fcf_rendite(fd_basis).rohwert == pytest.approx((150 - 50) / 2000 * 100)
    fd_basis.fcf_abzug_aktienverguetung = False
    assert k.fcf_rendite(fd_basis).rohwert == pytest.approx(150 / 2000 * 100)


def test_fcf_ohne_ausgewiesene_aktienverguetung(fd_basis):
    e = k.fcf_rendite(fd_basis)
    assert e.rohwert == pytest.approx(150 / 2000 * 100)
    assert "keine Aktienvergütung ausgewiesen" in e.details


def test_wachstum_geglaettet_daempft_ausreisser():
    """Ein einzelnes schwaches Endjahr (wie KO 2025) verzerrt die geglättete Rate deutlich weniger."""
    fd = k.Finanzdaten()
    werte = [100 * 1.08 ** i for i in range(11)]
    werte[-1] = werte[-2] * 0.6                         # Einbruch im letzten Jahr
    fd.jahre["umsatz"] = jahresreihe(werte)
    geglaettet = k.umsatz_cagr(fd).rohwert
    punkt_zu_punkt = ((werte[-1] / werte[-6]) ** (1 / 5) - 1) * 100
    assert punkt_zu_punkt < -2
    assert 0 < geglaettet < 8
    assert "Ø GJ" in k.umsatz_cagr(fd).details


def test_wachstum_ohne_glaettung_bei_wenigen_jahren():
    fd = k.Finanzdaten()
    fd.jahre["umsatz"] = jahresreihe([100 * 1.1 ** i for i in range(6)])
    e = k.umsatz_cagr(fd)
    assert e.rohwert == pytest.approx(10)
    assert "ohne Glättung" in e.hinweis


def _historie(fd, fcf_je_jahr=100, kurs=10):
    jahre = [date(2015 + i, 12, 31) for i in range(10)]
    fd.jahre["ocf"] = [w(fcf_je_jahr, d) for d in jahre]
    fd.jahre["capex"] = [w(0, d) for d in jahre]
    fd.jahre["aktien_verwaessert"] = [w(100, d) for d in jahre]
    fd.kurse = pd.Series(float(kurs), index=pd.bdate_range("2015-01-01", "2025-12-31"))


def test_fcf_rendite_historie(fd_basis):
    _historie(fd_basis)            # historisch: 100 / (100 × 10) = 10 %
    e = k.fcf_rendite_historie(fd_basis)
    aktuell = 150 / 2000 * 100     # 7,5 %
    assert e.rohwert == pytest.approx((aktuell / 10 - 1) * 100)


def test_erwartetes_wachstum_nimmt_niedrigeres():
    fd = k.Finanzdaten()
    fd.jahre["umsatz"] = jahresreihe([100 * 1.10 ** i for i in range(11)])           # 10 %
    fd.jahre["ocf"] = jahresreihe([50 * 1.04 ** i for i in range(11)])               # 4 %
    fd.jahre["capex"] = jahresreihe([0] * 11)
    fd.jahre["aktien_verwaessert"] = jahresreihe([100] * 11)
    g, _, grund = k.erwartetes_wachstum(fd)
    assert grund is None and g == pytest.approx(4)


def test_erwartetes_wachstum_begrenzt():
    fd = k.Finanzdaten()
    fd.jahre["umsatz"] = jahresreihe([100 * 1.30 ** i for i in range(11)])           # 30 %
    g, text, _ = k.erwartetes_wachstum(fd)
    assert g == pytest.approx(12) and "begrenzt" in text


def test_dcf_eingaben(fd_basis):
    fd_basis.jahre["umsatz"] = jahresreihe([100 * 1.05 ** i for i in range(11)])
    e = k.dcf_eingaben(fd_basis)
    assert e.grund is None
    assert e.fcf_ttm == pytest.approx(150)
    assert e.wachstum == pytest.approx(5)
    assert e.nettocash == pytest.approx(150 - 475)
    assert e.aktien == 100 and e.kurs == 20


def test_aktien_verwaesserung():
    fd = k.Finanzdaten()
    fd.jahre["aktien_verwaessert"] = jahresreihe([100, 99, 98, 97, 96, 95])
    assert k.aktien_verwaesserung(fd).rohwert == pytest.approx(((95 / 100) ** 0.2 - 1) * 100)


def test_roic_ueber_aktivseite(fd_basis):
    # 1525 = Bilanzsumme 2000 – Cash/Wertpapiere 150 – (kurzfr. Verb. 400 – kurzfr. Schulden 75)
    kapital, methode = k.investiertes_kapital(fd_basis, date(2025, 12, 31))
    assert kapital == pytest.approx(1525) and methode == "Aktivseite"


def test_roic_funktioniert_bei_negativem_eigenkapital():
    """Wie bei McDonald's: Eigenkapital negativ nach Rückkäufen, ROIC trotzdem berechenbar."""
    fd = k.Finanzdaten()
    jahre = [date(2021 + i, 12, 31) for i in range(5)]
    fd.jahre["ebit"] = [w(100, d) for d in jahre]
    for konzept, wert in {"bilanzsumme": 1000, "kurzfr_verbindlichkeiten": 200, "cash": 100, "eigenkapital": -300}.items():
        fd.bilanz[konzept] = [w(wert, d) for d in jahre]
    e = k.roic(fd)
    assert e.rohwert == pytest.approx(100 * (1 - 0.21) / 700 * 100)
