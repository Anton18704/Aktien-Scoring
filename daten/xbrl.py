"""Aufbereitung der SEC-"companyfacts" (XBRL) zu ``Finanzdaten``.

Unternehmen benennen dieselbe Position unterschiedlich und wechseln die
Bezeichnung über die Jahre. Für jedes Konzept gibt es deshalb eine Liste
möglicher XBRL-Felder in Reihenfolge der Priorität. Pro Zeitraum wird der
Wert des ersten vorhandenen Feldes genommen; bei mehreren Meldungen
desselben Zeitraums die zuletzt eingereichte (berücksichtigt Korrekturen).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from kern.kennzahlen import Finanzdaten, Wert

# ---------------------------------------------------------------------
# Konzept -> mögliche XBRL-Felder (Taxonomie:Feld)
# ---------------------------------------------------------------------

ZEITRAUM = {
    "umsatz": ["us-gaap:Revenues", "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
               "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax", "us-gaap:SalesRevenueNet",
               "us-gaap:SalesRevenueGoodsNet", "us-gaap:RevenuesNetOfInterestExpense",
               "ifrs-full:Revenue", "ifrs-full:RevenueFromContractsWithCustomers"],
    "bruttogewinn": ["us-gaap:GrossProfit", "ifrs-full:GrossProfit"],
    "herstellkosten": ["us-gaap:CostOfRevenue", "us-gaap:CostOfGoodsAndServicesSold", "us-gaap:CostOfGoodsSold",
                       "us-gaap:CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization",
                       "ifrs-full:CostOfSales"],
    "ebit": ["us-gaap:OperatingIncomeLoss", "ifrs-full:ProfitLossFromOperatingActivities"],
    "nettogewinn": ["us-gaap:NetIncomeLoss", "us-gaap:ProfitLoss",
                    "ifrs-full:ProfitLossAttributableToOwnersOfParent", "ifrs-full:ProfitLoss"],
    "ocf": ["us-gaap:NetCashProvidedByUsedInOperatingActivities",
            "us-gaap:NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
            "ifrs-full:CashFlowsFromUsedInOperatingActivities"],
    "capex": ["us-gaap:PaymentsToAcquirePropertyPlantAndEquipment", "us-gaap:PaymentsToAcquireProductiveAssets",
              "us-gaap:PaymentsForCapitalImprovements",
              "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
              "ifrs-full:PurchaseOfPropertyPlantAndEquipment"],
    "abschreibungen": ["us-gaap:DepreciationDepletionAndAmortization", "us-gaap:DepreciationAmortizationAndAccretionNet",
                       "us-gaap:DepreciationAndAmortization", "us-gaap:Depreciation",
                       "ifrs-full:AdjustmentsForDepreciationAndAmortisationExpense",
                       "ifrs-full:DepreciationAndAmortisationExpense"],
    "zinsaufwand": ["us-gaap:InterestExpense", "us-gaap:InterestExpenseNonoperating", "us-gaap:InterestExpenseDebt",
                    "us-gaap:InterestAndDebtExpense", "ifrs-full:InterestExpense", "ifrs-full:FinanceCosts"],
    "steuern": ["us-gaap:IncomeTaxExpenseBenefit", "ifrs-full:IncomeTaxExpenseContinuingOperations"],
    "vorsteuergewinn": [
        "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "ifrs-full:ProfitLossBeforeTax"],
    "dividenden": ["us-gaap:PaymentsOfDividends", "us-gaap:PaymentsOfDividendsCommonStock",
                   "us-gaap:PaymentsOfOrdinaryDividends", "ifrs-full:DividendsPaidClassifiedAsFinancingActivities",
                   "ifrs-full:DividendsPaid"],
    "rueckkaeufe": ["us-gaap:PaymentsForRepurchaseOfCommonStock", "us-gaap:PaymentsForRepurchaseOfEquity",
                    "ifrs-full:PaymentsToAcquireOrRedeemEntitysShares"],
    "aktienausgabe": ["us-gaap:ProceedsFromIssuanceOfCommonStock", "us-gaap:ProceedsFromStockOptionsExercised",
                      "us-gaap:ProceedsFromIssuanceOfSharesUnderIncentiveAndShareBasedCompensationPlans",
                      "ifrs-full:ProceedsFromIssuingShares"],
    "aktien_verwaessert": ["us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
                           "ifrs-full:AdjustedWeightedAverageShares"],
}

STICHTAG = {
    "bilanzsumme": ["us-gaap:Assets", "ifrs-full:Assets"],
    "umlaufvermoegen": ["us-gaap:AssetsCurrent", "ifrs-full:CurrentAssets"],
    "kurzfr_verbindlichkeiten": ["us-gaap:LiabilitiesCurrent", "ifrs-full:CurrentLiabilities"],
    "verbindlichkeiten": ["us-gaap:Liabilities", "ifrs-full:Liabilities"],
    "eigenkapital": ["us-gaap:StockholdersEquity",
                     "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                     "ifrs-full:EquityAttributableToOwnersOfParent", "ifrs-full:Equity"],
    "gewinnruecklagen": ["us-gaap:RetainedEarningsAccumulatedDeficit", "ifrs-full:RetainedEarnings"],
    "cash": ["us-gaap:CashAndCashEquivalentsAtCarryingValue",
             "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
             "us-gaap:Cash", "us-gaap:CashAndDueFromBanks", "ifrs-full:CashAndCashEquivalents"],
    "ltd_gesamt": ["us-gaap:LongTermDebt", "ifrs-full:Borrowings"],
    "ltd_langfristig": ["us-gaap:LongTermDebtNoncurrent", "us-gaap:LongTermDebtAndCapitalLeaseObligations",
                        "ifrs-full:NoncurrentPortionOfNoncurrentBorrowings", "ifrs-full:LongtermBorrowings"],
    "ltd_kurzfristig": ["us-gaap:LongTermDebtCurrent", "us-gaap:LongTermDebtAndCapitalLeaseObligationsCurrent",
                        "ifrs-full:CurrentPortionOfLongtermBorrowings"],
    "schulden_kurzfristig_gesamt": ["us-gaap:DebtCurrent",
                                    "ifrs-full:CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings"],
    "kurzfr_kredite": ["us-gaap:ShortTermBorrowings", "ifrs-full:ShorttermBorrowings"],
    "commercial_paper": ["us-gaap:CommercialPaper"],
    "aktien_bilanz": ["us-gaap:CommonStockSharesOutstanding"],
}

# Konzepte, deren Felder addiert werden (getrennte Bilanzposten), statt das erste zu nehmen.
# Jede innere Liste ist wieder eine Prioritätenliste.
SUMME = {
    "kurzfr_wertpapiere": [["us-gaap:MarketableSecuritiesCurrent",
                            "us-gaap:AvailableForSaleSecuritiesDebtSecuritiesCurrent",
                            "us-gaap:AvailableForSaleSecuritiesCurrent"],
                           ["us-gaap:ShortTermInvestments", "ifrs-full:CurrentInvestments"]],
}

AKTIEN_KONZEPTE = {"aktien_verwaessert", "aktien_bilanz"}



@dataclass
class Fakt:
    wert: float
    ende: date
    start: date | None
    eingereicht: date
    form: str
    feld: str
    prio: int

    @property
    def tage(self) -> int:
        return (self.ende - self.start).days + 1 if self.start else 0

    def quelle(self) -> str:
        feld = self.feld.split(":", 1)[1]
        return f"EDGAR {self.form} {feld} (eingereicht {self.eingereicht.isoformat()})"

    def als_wert(self, faktor: float = 1.0) -> Wert:
        return Wert(self.wert * faktor, self.ende, self.quelle(), self.start)


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


def berichtswaehrung(facts: dict) -> str:
    """Währung, in der die Bilanzsumme zuletzt berichtet wurde."""
    for feld in ("us-gaap:Assets", "ifrs-full:Assets", "us-gaap:Revenues", "ifrs-full:Revenue"):
        tax, name = feld.split(":")
        einheiten = facts.get("facts", {}).get(tax, {}).get(name, {}).get("units", {})
        kandidaten = [(max(f["end"] for f in liste), u) for u, liste in einheiten.items() if "/" not in u and liste]
        if kandidaten:
            return max(kandidaten)[1]
    return "USD"


def fakten(facts: dict, felder: list[str], einheit: str) -> list[Fakt]:
    ergebnis = []
    for prio, feld in enumerate(felder):
        tax, name = feld.split(":")
        liste = facts.get("facts", {}).get(tax, {}).get(name, {}).get("units", {}).get(einheit, [])
        for f in liste:
            try:
                ergebnis.append(Fakt(float(f["val"]), _d(f["end"]), _d(f["start"]) if f.get("start") else None,
                                     _d(f["filed"]), f.get("form", ""), feld, prio))
            except (KeyError, ValueError, TypeError):
                continue
    return ergebnis


def _beste(liste: list[Fakt]) -> Fakt:
    """Höchste Priorität (kleinste Zahl), dann die zuletzt eingereichte Meldung."""
    return min(liste, key=lambda f: (f.prio, -f.eingereicht.toordinal()))


def nach_zeitraum(fs: list[Fakt]) -> list[Fakt]:
    gruppen = defaultdict(list)
    for f in fs:
        if f.start:
            gruppen[(f.start, f.ende)].append(f)
    return sorted((_beste(g) for g in gruppen.values()), key=lambda f: (f.ende, f.start))


def nach_stichtag(fs: list[Fakt]) -> list[Fakt]:
    gruppen = defaultdict(list)
    for f in fs:
        if f.start is None:
            gruppen[f.ende].append(f)
    return sorted((_beste(g) for g in gruppen.values()), key=lambda f: f.ende)


def ist_jahr(f: Fakt) -> bool:
    return 350 <= f.tage <= 380


def jahreswerte(zeitraeume: list[Fakt]) -> list[Fakt]:
    """Ein Wert pro Geschäftsjahr (Zeitraum ca. 12 Monate), nach Enddatum sortiert."""
    pro_ende: dict[date, Fakt] = {}
    for f in zeitraeume:
        if ist_jahr(f):
            bisher = pro_ende.get(f.ende)
            if bisher is None or (f.prio, -f.eingereicht.toordinal()) < (bisher.prio, -bisher.eingereicht.toordinal()):
                pro_ende[f.ende] = f
    return [pro_ende[k] for k in sorted(pro_ende)]


def _passend(liste: list[Fakt], ende: date, tage: int | None = None, toleranz: int = 10) -> Fakt | None:
    treffer = [f for f in liste if abs((f.ende - ende).days) <= toleranz
               and (tage is None or abs(f.tage - tage) <= 10)]
    return min(treffer, key=lambda f: abs((f.ende - ende).days)) if treffer else None


def letzte_12_monate(zeitraeume: list[Fakt], faktor: float = 1.0) -> tuple[Wert | None, bool]:
    """Wert der letzten 12 Monate.

    Rechenweg: letztes Geschäftsjahr + laufendes Jahr bis heute – gleicher Zeitraum im Vorjahr.
    Ersatzweise die Summe der letzten vier Quartale. Gibt es keine Quartalsdaten,
    wird das letzte Geschäftsjahr genommen (zweiter Rückgabewert = True).
    """
    gueltig = [f for f in zeitraeume if 80 <= f.tage <= 380]
    if not gueltig:
        return None, False
    jahre = jahreswerte(zeitraeume)
    letztes_ende = max(f.ende for f in gueltig)
    am_ende = [f for f in gueltig if f.ende == letztes_ende]
    laufend = max(am_ende, key=lambda f: f.tage)

    if ist_jahr(laufend):
        nur_jahre = all(ist_jahr(f) for f in gueltig)
        return laufend.als_wert(faktor), nur_jahre

    gj = _passend(jahre, laufend.start - timedelta(days=1), toleranz=7)
    vorjahr = _passend(gueltig, laufend.ende - timedelta(days=364), tage=laufend.tage, toleranz=10)
    if gj and vorjahr and not ist_jahr(vorjahr):
        wert = gj.wert + laufend.wert - vorjahr.wert
        quelle = (f"12 Monate bis {laufend.ende.isoformat()}: GJ {gj.ende.isoformat()} + "
                  f"{laufend.tage // 30} Monate – Vorjahreszeitraum; {laufend.quelle()}")
        return Wert(wert * faktor, laufend.ende, quelle, laufend.start), False

    # Ersatz: vier aufeinanderfolgende Quartale
    quartale = [f for f in gueltig if 80 <= f.tage <= 100]
    kette, ende = [], letztes_ende
    for _ in range(4):
        q = _passend(quartale, ende, tage=91, toleranz=7)
        if q is None:
            break
        kette.append(q)
        ende = q.start - timedelta(days=1)
    if len(kette) == 4:
        quelle = f"Summe 4 Quartale bis {letztes_ende.isoformat()}; {kette[0].quelle()}"
        return Wert(sum(q.wert for q in kette) * faktor, letztes_ende, quelle, kette[-1].start), False

    if jahre:
        return jahre[-1].als_wert(faktor), True
    return None, False


def split_faktor(splits: list[tuple[date, float]], eingereicht: date) -> float:
    """Aktienzahlen auf heutige Basis bringen: alle Splits nach dem Einreichungsdatum anwenden."""
    faktor = 1.0
    for tag, verhaeltnis in splits:
        if tag > eingereicht and verhaeltnis > 0:
            faktor *= verhaeltnis
    return faktor


def finanzdaten_aus(facts: dict, kurse=None) -> tuple[Finanzdaten, list[str]]:
    """Baut ``Finanzdaten`` aus companyfacts und (optional) Kursdaten. Liefert auch Hinweise."""
    hinweise: list[str] = []
    waehrung = berichtswaehrung(facts)
    splits = kurse.splits if kurse is not None else []
    fd = Finanzdaten(waehrung=waehrung)
    nur_jahre = True

    for konzept, felder in ZEITRAUM.items():
        einheit = "shares" if konzept in AKTIEN_KONZEPTE else waehrung
        zr = nach_zeitraum(fakten(facts, felder, einheit))
        if not zr:
            continue
        if konzept in AKTIEN_KONZEPTE:
            fd.jahre[konzept] = [f.als_wert(split_faktor(splits, f.eingereicht)) for f in jahreswerte(zr)]
        else:
            fd.jahre[konzept] = [f.als_wert() for f in jahreswerte(zr)]
            ttm, ist_gj = letzte_12_monate(zr)
            if ttm is not None:
                fd.ttm[konzept] = ttm
                if not ist_gj:
                    nur_jahre = False
    fd.ttm_ist_geschaeftsjahr = nur_jahre and bool(fd.ttm)
    if fd.ttm_ist_geschaeftsjahr:
        hinweise.append("Keine Quartalsdaten gefunden: statt der letzten 12 Monate wird das letzte Geschäftsjahr verwendet.")

    for konzept, felder in STICHTAG.items():
        einheit = "shares" if konzept in AKTIEN_KONZEPTE else waehrung
        st = nach_stichtag(fakten(facts, felder, einheit))
        if st:
            fd.bilanz[konzept] = [f.als_wert(split_faktor(splits, f.eingereicht) if konzept in AKTIEN_KONZEPTE else 1.0)
                                  for f in st]

    for konzept, gruppen in SUMME.items():
        summen: dict[date, list[Fakt]] = defaultdict(list)
        for felder in gruppen:
            for f in nach_stichtag(fakten(facts, felder, waehrung)):
                summen[f.ende].append(f)
        if summen:
            fd.bilanz[konzept] = [Wert(sum(f.wert for f in fs), d, "; ".join(f.quelle() for f in fs))
                                  for d, fs in sorted(summen.items())]

    _aktien_aktuell(fd, facts, splits, hinweise)

    if kurse is not None and kurse.close is not None and not kurse.close.empty:
        fd.kurse = kurse.close
        fd.kurs_waehrung = kurse.waehrung
        fd.kurs_quelle = kurse.quelle
        letzter = kurse.close.index[-1]
        fd.kurs_aktuell = Wert(float(kurse.close.iloc[-1]), letzter.date(),
                               f"Schlusskurs {letzter.date().isoformat()} ({kurse.quelle})")
        if kurse.waehrung and kurse.waehrung != waehrung:
            hinweise.append(f"Kurs in {kurse.waehrung}, Abschluss in {waehrung}: Kennzahlen mit "
                            "Marktkapitalisierung werden ohne Währungsumrechnung ausgelassen.")
    return fd, hinweise


def _aktien_aktuell(fd: Finanzdaten, facts: dict, splits, hinweise: list[str]) -> None:
    """Aktuelle Aktienanzahl: Deckblatt des letzten Berichts (dei), sonst Bilanz, sonst verwässerter Durchschnitt."""
    dei = nach_stichtag(fakten(facts, ["dei:EntityCommonStockSharesOutstanding"], "shares"))
    verw = nach_zeitraum(fakten(facts, ZEITRAUM["aktien_verwaessert"], "shares"))
    verw_letzt = verw[-1].als_wert(split_faktor(splits, verw[-1].eingereicht)) if verw else None

    kandidat = None
    if dei:
        letzt = dei[-1]
        # Mehrere Aktiengattungen am selben Stichtag (ohne Dimension gemeldet) werden addiert.
        gleich = [f for f in fakten(facts, ["dei:EntityCommonStockSharesOutstanding"], "shares")
                  if f.ende == letzt.ende and f.eingereicht == letzt.eingereicht]
        werte = {f.wert for f in gleich}
        summe = sum(werte)
        faktor = split_faktor(splits, letzt.eingereicht)
        kandidat = Wert(summe * faktor, letzt.ende, f"EDGAR {letzt.form} Deckblatt EntityCommonStockSharesOutstanding "
                                                    f"(eingereicht {letzt.eingereicht.isoformat()})")
        if len(werte) > 1:
            hinweise.append(f"Aktienanzahl aus {len(werte)} Aktiengattungen addiert.")
    elif fd.bilanz.get("aktien_bilanz"):
        kandidat = fd.bilanz["aktien_bilanz"][-1]

    if kandidat and verw_letzt and kandidat.wert < 0.5 * verw_letzt.wert:
        hinweise.append("Aktienanzahl vom Deckblatt deutlich kleiner als die verwässerte Anzahl "
                        "(vermutlich mehrere Aktiengattungen) – verwässerte Anzahl verwendet.")
        kandidat = None
    fd.aktien_aktuell = kandidat or verw_letzt
    if fd.aktien_aktuell is None:
        hinweise.append("Keine Aktienanzahl gefunden.")


def schluss_kurse_als_reihe(daten: dict[str, float]) -> pd.Series:
    """Hilfsfunktion für Tests: {'2020-01-02': 100.0, ...} -> pd.Series."""
    return pd.Series(list(daten.values()), index=pd.to_datetime(list(daten.keys()))).sort_index()
