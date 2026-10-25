from datetime import date

import pandas as pd
import pytest

from daten import xbrl
from daten.kurse import Kursdaten


def fakt(val, start, end, filed, form="10-Q"):
    d = {"val": val, "end": end, "filed": filed, "form": form}
    if start:
        d["start"] = start
    return d


def facts_mit(felder: dict) -> dict:
    """{'us-gaap:Revenues': ('USD', [fakt, ...])} -> companyfacts-Struktur"""
    out = {"facts": {}}
    for feld, (einheit, liste) in felder.items():
        tax, name = feld.split(":")
        out["facts"].setdefault(tax, {})[name] = {"units": {einheit: liste}}
    return out


def test_12_monate_aus_jahr_plus_laufendem_jahr():
    zr = xbrl.nach_zeitraum(xbrl.fakten(facts_mit({"us-gaap:Revenues": ("USD", [
        fakt(1000, "2024-01-01", "2024-12-31", "2025-02-10", "10-K"),
        fakt(500, "2024-01-01", "2024-06-30", "2024-08-01"),
        fakt(600, "2025-01-01", "2025-06-30", "2025-08-01"),
        fakt(320, "2025-04-01", "2025-06-30", "2025-08-01"),
    ])}), ["us-gaap:Revenues"], "USD"))
    wert, ist_gj = xbrl.letzte_12_monate(zr)
    assert wert.wert == 1000 + 600 - 500
    assert wert.ende == date(2025, 6, 30)
    assert not ist_gj


def test_12_monate_im_ersten_quartal():
    zr = xbrl.nach_zeitraum(xbrl.fakten(facts_mit({"us-gaap:Revenues": ("USD", [
        fakt(1000, "2024-01-01", "2024-12-31", "2025-02-10", "10-K"),
        fakt(200, "2024-01-01", "2024-03-31", "2024-05-01"),
        fakt(260, "2025-01-01", "2025-03-31", "2025-05-01"),
    ])}), ["us-gaap:Revenues"], "USD"))
    assert xbrl.letzte_12_monate(zr)[0].wert == 1060


def test_12_monate_aus_vier_quartalen():
    zr = xbrl.nach_zeitraum(xbrl.fakten(facts_mit({"us-gaap:Revenues": ("USD", [
        fakt(100, "2024-07-01", "2024-09-30", "2024-11-01"),
        fakt(110, "2024-10-01", "2024-12-31", "2025-02-01"),
        fakt(120, "2025-01-01", "2025-03-31", "2025-05-01"),
        fakt(130, "2025-04-01", "2025-06-30", "2025-08-01"),
    ])}), ["us-gaap:Revenues"], "USD"))
    assert xbrl.letzte_12_monate(zr)[0].wert == 460


def test_nur_jahreswerte_wird_markiert():
    zr = xbrl.nach_zeitraum(xbrl.fakten(facts_mit({"ifrs-full:Revenue": ("EUR", [
        fakt(900, "2023-01-01", "2023-12-31", "2024-03-01", "20-F"),
        fakt(1000, "2024-01-01", "2024-12-31", "2025-03-01", "20-F"),
    ])}), ["ifrs-full:Revenue"], "EUR"))
    wert, ist_gj = xbrl.letzte_12_monate(zr)
    assert wert.wert == 1000 and ist_gj


def test_korrektur_ueberschreibt_erstmeldung():
    zr = xbrl.nach_zeitraum(xbrl.fakten(facts_mit({"us-gaap:Revenues": ("USD", [
        fakt(1000, "2023-01-01", "2023-12-31", "2024-02-10", "10-K"),
        fakt(1050, "2023-01-01", "2023-12-31", "2025-02-10", "10-K"),   # im Folgejahr korrigiert
    ])}), ["us-gaap:Revenues"], "USD"))
    assert xbrl.jahreswerte(zr)[0].wert == 1050


def test_feldwechsel_wird_zusammengefuehrt():
    facts = facts_mit({
        "us-gaap:SalesRevenueNet": ("USD", [fakt(800, "2016-01-01", "2016-12-31", "2017-02-01", "10-K")]),
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax":
            ("USD", [fakt(900, "2018-01-01", "2018-12-31", "2019-02-01", "10-K")]),
    })
    zr = xbrl.nach_zeitraum(xbrl.fakten(facts, xbrl.ZEITRAUM["umsatz"], "USD"))
    assert [f.wert for f in xbrl.jahreswerte(zr)] == [800, 900]


def test_split_faktor():
    splits = [(date(2020, 8, 31), 4.0), (date(2014, 6, 9), 7.0)]
    assert xbrl.split_faktor(splits, date(2019, 11, 1)) == 4.0
    assert xbrl.split_faktor(splits, date(2013, 11, 1)) == 28.0
    assert xbrl.split_faktor(splits, date(2021, 1, 1)) == 1.0


def test_berichtswaehrung():
    facts = facts_mit({"ifrs-full:Assets": ("EUR", [fakt(1, None, "2024-12-31", "2025-03-01")])})
    assert xbrl.berichtswaehrung(facts) == "EUR"


def test_finanzdaten_aus_mit_split_und_kursen():
    facts = facts_mit({
        "us-gaap:Revenues": ("USD", [fakt(1000, "2019-01-01", "2019-12-31", "2020-02-01", "10-K")]),
        "us-gaap:Assets": ("USD", [fakt(5000, None, "2019-12-31", "2020-02-01", "10-K")]),
        "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding":
            ("shares", [fakt(100, "2019-01-01", "2019-12-31", "2020-02-01", "10-K")]),
        "dei:EntityCommonStockSharesOutstanding": ("shares", [fakt(98, None, "2020-01-20", "2020-02-01", "10-K")]),
    })
    kurse = Kursdaten(pd.Series([10.0, 11.0], index=pd.to_datetime(["2025-06-02", "2025-06-03"])),
                      splits=[(date(2020, 8, 31), 4.0)], waehrung="USD", quelle="test")
    fd, hinweise = xbrl.finanzdaten_aus(facts, kurse)
    assert fd.jahre["aktien_verwaessert"][0].wert == 400          # Split 4:1 nach Einreichung
    assert fd.aktien_aktuell.wert == 98 * 4
    assert fd.kurs_aktuell.wert == 11.0
    assert fd.ttm["umsatz"].wert == 1000
    assert fd.ttm_ist_geschaeftsjahr


def test_summenkonzept_wertpapiere():
    facts = facts_mit({
        "us-gaap:MarketableSecuritiesCurrent": ("USD", [fakt(30, None, "2025-12-31", "2026-02-01")]),
        "us-gaap:ShortTermInvestments": ("USD", [fakt(20, None, "2025-12-31", "2026-02-01")]),
        "us-gaap:Assets": ("USD", [fakt(1, None, "2025-12-31", "2026-02-01")]),
    })
    fd, _ = xbrl.finanzdaten_aus(facts)
    assert fd.bilanz["kurzfr_wertpapiere"][0].wert == 50


def test_veraltete_12_monats_werte_werden_entfernt():
    """Wie bei Apple: Zinsaufwand nur bis 2023 gemeldet, alles andere bis 2026."""
    facts = facts_mit({
        "us-gaap:Revenues": ("USD", [fakt(1000, "2025-01-01", "2025-12-31", "2026-02-01", "10-K")]),
        "us-gaap:InterestExpense": ("USD", [fakt(30, "2023-01-01", "2023-12-31", "2024-02-01", "10-K")]),
    })
    fd, hinweise = xbrl.finanzdaten_aus(facts)
    assert "zinsaufwand" not in fd.ttm
    assert "umsatz" in fd.ttm
    assert any("Zinsaufwand" in h for h in hinweise)
    assert fd.jahre["zinsaufwand"][0].wert == 30     # Jahreswerte bleiben für die Historie erhalten
