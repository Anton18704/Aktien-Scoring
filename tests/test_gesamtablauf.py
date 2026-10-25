"""Gesamter Weg von companyfacts-Struktur über Finanzdaten bis zu allen 14 Kennzahlen."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from daten.kurse import Kursdaten
from daten.xbrl import finanzdaten_aus
from kern.kennzahlen import alle_berechnen


def _fakt(val, end, filed, start=None, form="10-K"):
    d = {"val": val, "end": end, "filed": filed, "form": form}
    if start:
        d["start"] = start
    return d


def beispiel_facts():
    """Fiktive Firma: Geschäftsjahr = Kalenderjahr, 2015–2025, plus erstes Halbjahr 2026."""
    dauer = {k: [] for k in ["Revenues", "GrossProfit", "OperatingIncomeLoss", "NetIncomeLoss",
                             "NetCashProvidedByUsedInOperatingActivities", "PaymentsToAcquirePropertyPlantAndEquipment",
                             "DepreciationDepletionAndAmortization", "InterestExpense", "IncomeTaxExpenseBenefit",
                             "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                             "PaymentsOfDividends", "PaymentsForRepurchaseOfCommonStock"]}
    aktien, stichtag = [], {k: [] for k in ["Assets", "AssetsCurrent", "LiabilitiesCurrent", "Liabilities",
                                             "StockholdersEquity", "RetainedEarningsAccumulatedDeficit",
                                             "CashAndCashEquivalentsAtCarryingValue", "LongTermDebtNoncurrent"]}
    for i, jahr in enumerate(range(2015, 2026)):
        u = 1000 * 1.08 ** i
        s, e, f = f"{jahr}-01-01", f"{jahr}-12-31", f"{jahr + 1}-02-15"
        werte = {"Revenues": u, "GrossProfit": u * 0.4, "OperatingIncomeLoss": u * 0.2, "NetIncomeLoss": u * 0.15,
                 "NetCashProvidedByUsedInOperatingActivities": u * 0.18,
                 "PaymentsToAcquirePropertyPlantAndEquipment": u * 0.03,
                 "DepreciationDepletionAndAmortization": u * 0.05, "InterestExpense": u * 0.01,
                 "IncomeTaxExpenseBenefit": u * 0.04,
                 "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": u * 0.19,
                 "PaymentsOfDividends": u * 0.05, "PaymentsForRepurchaseOfCommonStock": u * 0.04}
        for k, v in werte.items():
            dauer[k].append(_fakt(v, e, f, s))
        aktien.append(_fakt(100 - i, e, f, s))
        for k, v in {"Assets": u * 2, "AssetsCurrent": u * 0.6, "LiabilitiesCurrent": u * 0.4, "Liabilities": u * 1.2,
                     "StockholdersEquity": u * 0.8, "RetainedEarningsAccumulatedDeficit": u * 0.5,
                     "CashAndCashEquivalentsAtCarryingValue": u * 0.1, "LongTermDebtNoncurrent": u * 0.3}.items():
            stichtag[k].append(_fakt(v, e, f))
    # Halbjahre 2025 und 2026
    for k in dauer:
        jahr25 = dauer[k][-1]["val"]
        dauer[k].append(_fakt(jahr25 * 0.48, "2025-06-30", "2025-08-01", "2025-01-01", "10-Q"))
        dauer[k].append(_fakt(jahr25 * 0.52, "2026-06-30", "2026-08-01", "2026-01-01", "10-Q"))
    for k in stichtag:
        stichtag[k].append(_fakt(stichtag[k][-1]["val"] * 1.03, "2026-06-30", "2026-08-01", form="10-Q"))

    gaap = {k: {"units": {"USD": v}} for k, v in {**dauer, **stichtag}.items()}
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = {"units": {"shares": aktien}}
    return {"facts": {"us-gaap": gaap, "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        _fakt(89, "2026-07-20", "2026-08-01", form="10-Q")]}}}}}


def test_alle_kennzahlen_aus_rohdaten():
    tage = pd.bdate_range("2014-06-01", "2026-09-30")
    kurs = pd.Series(np.linspace(20, 60, len(tage)), index=tage)
    kurs.loc["2022-01-01":"2022-12-31"] *= 0.7      # ein Einbruch von 30 %
    kd = Kursdaten(kurs, [], "USD", "test")
    fd, hinweise = finanzdaten_aus(beispiel_facts(), kd)
    ergebnisse = {e.schluessel: e for e in alle_berechnen(fd)}

    # Kein Fehler, alle 14 berechnet
    assert all(e.grund is None for e in ergebnisse.values()), {k: e.grund for k, e in ergebnisse.items() if e.grund}

    u25 = 1000 * 1.08 ** 10
    ttm_umsatz = u25 + u25 * 0.52 - u25 * 0.48
    assert fd.ttm["umsatz"].wert == pytest.approx(ttm_umsatz)
    assert fd.ttm["umsatz"].ende == date(2026, 6, 30)

    mk = 89 * 60.0
    assert ergebnisse["fcf_rendite"].rohwert == pytest.approx(ttm_umsatz * 0.15 / mk * 100)
    assert ergebnisse["umsatz_cagr"].rohwert == pytest.approx(8.0)
    assert ergebnisse["umsatz_bestaendigkeit"].rohwert == 10
    assert ergebnisse["bruttomarge_stabilitaet"].rohwert == pytest.approx(0, abs=1e-9)
    assert ergebnisse["fcf_umwandlung"].rohwert == pytest.approx(100)
    # Entschuldungsdauer: Nettoschulden ÷ FCF der letzten 12 Monate
    assert ergebnisse["entschuldungsdauer"].rohwert == pytest.approx(
        (u25 * 1.03 * 0.3 - u25 * 1.03 * 0.1) / (ttm_umsatz * 0.15))
    assert ergebnisse["zinsdeckung"].rohwert == pytest.approx(20)
    assert ergebnisse["max_kursrueckgang"].rohwert == pytest.approx(30, abs=1)
    # ROIC: EBIT 20 % vom Umsatz × (1 – Steuersatz) ÷ investiertes Kapital (Aktivseite, Ø Anfang/Ende)
    # Kapital = Bilanzsumme 2,0 – Cash 0,1 – kurzfr. Verb. 0,4 = 1,5 × Umsatz; Vorjahr 1,5 × Umsatz / 1,08
    kapital = 1.5 * (1 + 1 / 1.08) / 2
    assert ergebnisse["roic"].rohwert == pytest.approx(0.2 * (1 - 0.04 / 0.19) / kapital * 100)
    # FCF je Aktie wächst schneller als der Umsatz, weil die Aktienanzahl sinkt
    assert ergebnisse["fcf_je_aktie_cagr"].rohwert > 8
    assert ergebnisse["nettoverschuldung_ebitda"].rohwert == pytest.approx(
        (u25 * 1.03 * 0.3 - u25 * 1.03 * 0.1) / (ttm_umsatz * 0.25))
