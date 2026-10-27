"""Eigenes DCF-Modell (Seite „DCF-Modell“): Annahmen → Free-Cashflow-Rechnung → Abzinsung.

Klassisches Analystenmodell mit dem Free Cashflow an alle Kapitalgeber („unlevered“):

    Umsatz × EBIT-Marge                     = EBIT
    – Steuern auf das EBIT                  = NOPAT (Gewinn nach Steuern, ohne Zinsen)
    + Abschreibungen – Investitionen (Capex) – Zunahme des Working Capitals
    = Free Cashflow

Abgezinst wird mit dem WACC (gewichtete Kapitalkosten):

    Eigenkapitalkosten = risikofreier Zins + Beta × Marktrisikoprämie
    WACC = EK-Anteil × EK-Kosten + FK-Anteil × FK-Zins × (1 – Steuersatz)
    Diskontfaktor im Jahr t = 1 ÷ (1 + WACC)^t

Nach dem letzten Prognosejahr folgt der Endwert: ewiges Wachstum (Gordon), Exit-Multiple
(Unternehmenswert ÷ EBITDA) oder der Durchschnitt aus beiden.
Unternehmenswert – Nettoschulden = Eigenkapitalwert; ÷ Aktienanzahl = fairer Wert je Aktie.

Alle Prozentwerte als Prozentzahl (4.5 = 4,5 %).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace

from kern.dcf import wachstumspfad

MINDESTABSTAND_GORDON = 1.0      # WACC muss mindestens so viele Prozentpunkte über dem ewigen Wachstum liegen
METHODEN = {"durchschnitt": "Durchschnitt aus beiden", "gordon": "ewiges Wachstum (Gordon)",
            "multiple": "Exit-Multiple (EV/EBITDA)"}


def _aus_dict(cls, d: dict):
    return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ModellBasis:
    """Zahlen aus den Abschlüssen, die bei jeder Analyse gesichert werden (JSON in der Datenbank)."""
    umsatz: float | None = None              # letzte 12 Monate
    ebit: float | None = None
    abschreibungen: float | None = None
    capex: float | None = None
    historie: list[dict] = field(default_factory=list)   # [{jahr, umsatz, ebit, abschreibungen, capex}], alt → neu
    nwc: float | None = None                 # Working Capital ohne Cash und Finanzschulden
    steuersatz: float = 21.0
    schulden: float = 0.0
    cash: float = 0.0                        # Cash + kurzfristige Wertpapiere
    langfr_wertpapiere: float = 0.0
    zinsaufwand: float | None = None
    aktien: float | None = None
    kurs: float | None = None
    waehrung: str = "USD"
    datenstand: str = ""
    quelle: str = ""
    grund: str | None = None

    def als_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def aus_dict(cls, d: dict) -> "ModellBasis":
        return _aus_dict(cls, d)


@dataclass
class Annahmen:
    """Alles, was man auf der Seite einstellen kann (wird mit dem Modell gespeichert)."""
    wachstum: list[float]                    # Umsatzwachstum je Prognosejahr, %
    ebit_marge: list[float]                  # EBIT-Marge je Prognosejahr, %
    steuersatz: float = 21.0
    abschr_quote: float = 3.0                # Abschreibungen in % vom Umsatz
    capex_quote: float = 3.0                 # Investitionen in % vom Umsatz
    nwc_quote: float = 0.0                   # Working Capital in % vom Umsatz
    rf: float = 4.25                         # risikofreier Zins
    beta: float = 1.0
    erp: float = 4.5                         # Marktrisikoprämie
    fk_zins: float = 5.5                     # Zinssatz auf Schulden vor Steuern
    fk_anteil: float = 0.0                   # Anteil Schulden am Gesamtkapital (Marktwerte), %
    wacc_manuell: float | None = None
    g_ewig: float = 2.5
    exit_multiple: float = 12.0              # Unternehmenswert ÷ EBITDA im letzten Jahr
    endwert_methode: str = "durchschnitt"
    mitte_jahr: bool = False                 # Cashflows fließen im Schnitt zur Jahresmitte
    umsatz_start: float | None = None        # None = Umsatz der letzten 12 Monate
    nettoschulden: float | None = None       # None = aus der Bilanz

    @property
    def jahre(self) -> int:
        return len(self.wachstum)

    @property
    def ek_kosten(self) -> float:
        return self.rf + self.beta * self.erp

    @property
    def wacc(self) -> float:
        if self.wacc_manuell is not None:
            return self.wacc_manuell
        fk = self.fk_anteil / 100
        return (1 - fk) * self.ek_kosten + fk * self.fk_zins * (1 - self.steuersatz / 100)

    def als_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def aus_dict(cls, d: dict) -> "Annahmen":
        return _aus_dict(cls, d)


# ---------------------------------------------------------------------
# Vorschlag aus den Abschlüssen
# ---------------------------------------------------------------------

def _quote(zaehler: str, jahre: list[dict], n: int) -> float | None:
    werte = [j[zaehler] / j["umsatz"] * 100 for j in jahre[-n:]
             if j.get(zaehler) is not None and j.get("umsatz")]
    return sum(werte) / len(werte) if werte else None


def kennzahlen_historie(b: ModellBasis) -> dict:
    """Durchschnittswerte der Vergangenheit, auf denen der Vorschlag beruht."""
    h = b.historie
    umsaetze = [j["umsatz"] for j in h if j.get("umsatz")]
    cagr = None
    if len(umsaetze) >= 2 and umsaetze[0] > 0 and umsaetze[-1] > 0:
        cagr = ((umsaetze[-1] / umsaetze[0]) ** (1 / (len(umsaetze) - 1)) - 1) * 100
    ttm = lambda x: x / b.umsatz * 100 if x is not None and b.umsatz else None  # noqa: E731
    return {
        "umsatz_cagr": cagr, "jahre_cagr": len(umsaetze) - 1,
        "ebit_marge_ttm": ttm(b.ebit), "ebit_marge_5j": _quote("ebit", h, 5),
        "abschr_quote_3j": _quote("abschreibungen", h, 3), "capex_quote_3j": _quote("capex", h, 3),
        "abschr_quote_ttm": ttm(b.abschreibungen), "capex_quote_ttm": ttm(b.capex),
        "nwc_quote": ttm(b.nwc),
    }


def vorschlag(b: ModellBasis, wachstum_start: float, rf: float, beta: float, erp: float,
              g_ewig: float = 2.5, exit_multiple: float = 12.0, jahre: int = 10, phase: int = 5) -> Annahmen:
    """Startwerte für die Annahmen: Wachstum wie im automatischen DCF, Margen und Quoten aus der Vergangenheit."""
    k = kennzahlen_historie(b)
    marge = next((x for x in (k["ebit_marge_5j"], k["ebit_marge_ttm"]) if x is not None), 10.0)
    fk_zins = rf + 1.5
    if b.schulden > 0 and b.zinsaufwand:
        fk_zins = min(max(b.zinsaufwand / b.schulden * 100, rf), rf + 8.0)
    mk = (b.aktien or 0) * (b.kurs or 0)
    fk_anteil = b.schulden / (b.schulden + mk) * 100 if b.schulden > 0 and mk > 0 else 0.0
    return Annahmen(
        wachstum=[round(g, 2) for g in wachstumspfad(wachstum_start, g_ewig, jahre, min(phase, jahre))],
        ebit_marge=[round(marge, 2)] * jahre,
        steuersatz=round(b.steuersatz, 1),
        abschr_quote=round(next((x for x in (k["abschr_quote_3j"], k["abschr_quote_ttm"]) if x is not None), 3.0), 2),
        capex_quote=round(next((x for x in (k["capex_quote_3j"], k["capex_quote_ttm"]) if x is not None), 3.0), 2),
        nwc_quote=round(k["nwc_quote"] or 0.0, 2),
        rf=round(rf, 2), beta=round(beta, 2), erp=erp, fk_zins=round(fk_zins, 2), fk_anteil=round(fk_anteil, 1),
        g_ewig=g_ewig, exit_multiple=round(exit_multiple, 1))


def linear(start: float, ende: float, jahre: int) -> list[float]:
    """Gleichmäßiger Übergang von ``start`` (Jahr 1) zu ``ende`` (letztes Jahr)."""
    if jahre <= 1:
        return [start] * jahre
    return [round(start + (ende - start) * t / (jahre - 1), 2) for t in range(jahre)]


# ---------------------------------------------------------------------
# Rechnung
# ---------------------------------------------------------------------

@dataclass
class ModellErgebnis:
    grund: str | None = None
    zeilen: list[dict] = field(default_factory=list)   # je Prognosejahr
    wacc: float | None = None
    ek_kosten: float | None = None
    fcf_letztes: float | None = None
    ebitda_letztes: float | None = None
    endwert_gordon: float | None = None
    endwert_multiple: float | None = None
    endwert: float | None = None
    endwert_text: str = ""
    endwert_zeit: float | None = None
    endwert_diskontfaktor: float | None = None
    endwert_barwert: float | None = None
    impl_multiple: float | None = None     # EV/EBITDA, das der Gordon-Endwert bedeutet
    impl_wachstum: float | None = None     # ewiges Wachstum, das der Multiple-Endwert bedeutet
    summe_barwerte: float | None = None
    unternehmenswert: float | None = None
    nettoschulden: float | None = None
    eigenkapitalwert: float | None = None
    aktien: float | None = None
    fairer_wert: float | None = None
    kurs: float | None = None
    sicherheitsmarge: float | None = None
    endwert_anteil: float | None = None
    hinweise: list[str] = field(default_factory=list)


def rechnen(a: Annahmen, b: ModellBasis) -> ModellErgebnis:
    erg = ModellErgebnis(kurs=b.kurs, aktien=b.aktien)
    umsatz0 = a.umsatz_start if a.umsatz_start is not None else b.umsatz
    if b.grund:
        erg.grund = b.grund
        return erg
    if not umsatz0 or umsatz0 <= 0:
        erg.grund = "kein Umsatz als Startwert"
        return erg
    if not b.aktien or b.aktien <= 0 or not b.kurs:
        erg.grund = "Aktienanzahl oder Kurs fehlt"
        return erg
    if not a.wachstum or len(a.wachstum) != len(a.ebit_marge):
        erg.grund = "Wachstum und EBIT-Marge brauchen je einen Wert pro Jahr"
        return erg
    r = a.wacc
    erg.wacc, erg.ek_kosten = r, a.ek_kosten
    if r <= 0:
        erg.grund = "Der Zinssatz (WACC) muss positiv sein"
        return erg

    umsatz_vorher, nwc_vorher = umsatz0, umsatz0 * a.nwc_quote / 100
    summe = 0.0
    for t, (g, m) in enumerate(zip(a.wachstum, a.ebit_marge), start=1):
        umsatz = umsatz_vorher * (1 + g / 100)
        ebit = umsatz * m / 100
        steuern = max(ebit, 0.0) * a.steuersatz / 100
        nopat = ebit - steuern
        abschr, capex = umsatz * a.abschr_quote / 100, umsatz * a.capex_quote / 100
        nwc = umsatz * a.nwc_quote / 100
        fcf = nopat + abschr - capex - (nwc - nwc_vorher)
        zeit = t - 0.5 if a.mitte_jahr else float(t)
        df = 1 / (1 + r / 100) ** zeit
        erg.zeilen.append({"jahr": t, "umsatz": umsatz, "wachstum": g, "ebit": ebit, "ebit_marge": m,
                           "steuern": steuern, "nopat": nopat, "abschreibungen": abschr, "capex": capex,
                           "delta_nwc": nwc - nwc_vorher, "fcf": fcf, "zinssatz": r, "zeit": zeit,
                           "diskontfaktor": df, "barwert": fcf * df})
        summe += fcf * df
        umsatz_vorher, nwc_vorher = umsatz, nwc
    letzte = erg.zeilen[-1]
    erg.summe_barwerte = summe
    erg.fcf_letztes = letzte["fcf"]
    erg.ebitda_letztes = letzte["ebit"] + letzte["abschreibungen"]

    # Endwert am Ende des letzten Prognosejahres
    if r - a.g_ewig >= MINDESTABSTAND_GORDON:
        erg.endwert_gordon = erg.fcf_letztes * (1 + a.g_ewig / 100) / ((r - a.g_ewig) / 100)
    if erg.ebitda_letztes > 0:
        erg.endwert_multiple = erg.ebitda_letztes * a.exit_multiple
    gordon, mult = erg.endwert_gordon, erg.endwert_multiple
    if a.endwert_methode == "gordon" and gordon is not None:
        erg.endwert, erg.endwert_text = gordon, METHODEN["gordon"]
    elif a.endwert_methode == "multiple" and mult is not None:
        erg.endwert, erg.endwert_text = mult, METHODEN["multiple"]
    elif gordon is not None and mult is not None:
        erg.endwert, erg.endwert_text = (gordon + mult) / 2, METHODEN["durchschnitt"]
    elif gordon is not None or mult is not None:
        erg.endwert = gordon if gordon is not None else mult
        erg.endwert_text = METHODEN["gordon" if gordon is not None else "multiple"]
        erg.hinweise.append("Gewählte Endwert-Methode nicht berechenbar – " + erg.endwert_text + " verwendet"
                            + (" (WACC zu nah am ewigen Wachstum)" if gordon is None else " (EBITDA nicht positiv)"))
    else:
        erg.grund = (f"Kein Endwert berechenbar: WACC muss mindestens {MINDESTABSTAND_GORDON:g} Prozentpunkte "
                     "über dem ewigen Wachstum liegen oder das EBITDA im letzten Jahr positiv sein")
        return erg
    if gordon is not None and erg.ebitda_letztes > 0:
        erg.impl_multiple = gordon / erg.ebitda_letztes
    if mult is not None and mult + erg.fcf_letztes != 0:
        erg.impl_wachstum = (mult * r / 100 - erg.fcf_letztes) / (mult + erg.fcf_letztes) * 100

    erg.endwert_zeit = float(a.jahre)
    erg.endwert_diskontfaktor = 1 / (1 + r / 100) ** erg.endwert_zeit
    erg.endwert_barwert = erg.endwert * erg.endwert_diskontfaktor
    erg.unternehmenswert = summe + erg.endwert_barwert
    erg.nettoschulden = a.nettoschulden if a.nettoschulden is not None else b.schulden - b.cash
    erg.eigenkapitalwert = erg.unternehmenswert - erg.nettoschulden
    erg.fairer_wert = erg.eigenkapitalwert / b.aktien
    erg.sicherheitsmarge = ((erg.fairer_wert - b.kurs) / erg.fairer_wert * 100) if erg.fairer_wert > 0 else -100.0
    if erg.unternehmenswert > 0:
        erg.endwert_anteil = erg.endwert_barwert / erg.unternehmenswert * 100
    if erg.endwert_anteil is not None and erg.endwert_anteil > 85:
        erg.hinweise.append(f"Der Endwert macht {erg.endwert_anteil:.0f} % des Werts aus – das Ergebnis hängt "
                            "fast nur an ewigem Wachstum, WACC und Multiple.")
    if a.g_ewig > a.rf:
        erg.hinweise.append("Das ewige Wachstum liegt über dem risikofreien Zins – auf Dauer wächst kaum eine "
                            "Firma schneller als die Gesamtwirtschaft.")
    return erg


def empfindlichkeit(a: Annahmen, b: ModellBasis, art: str = "wachstum") -> dict:
    """Fairer Wert je Aktie bei anderem WACC (Zeilen) und ewigem Wachstum bzw. Exit-Multiple (Spalten)."""
    r0 = a.wacc
    zeilen = [r0 + d for d in (-1.0, -0.5, 0.0, 0.5, 1.0)]
    if art == "wachstum":
        spalten = [a.g_ewig + d for d in (-1.0, -0.5, 0.0, 0.5, 1.0)]
        variante = lambda r, x: replace(a, wacc_manuell=r, g_ewig=x)  # noqa: E731
    else:
        spalten = [max(a.exit_multiple + d, 1.0) for d in (-4.0, -2.0, 0.0, 2.0, 4.0)]
        variante = lambda r, x: replace(a, wacc_manuell=r, exit_multiple=x)  # noqa: E731
    werte = [[rechnen(variante(r, x), b).fairer_wert for x in spalten] for r in zeilen]
    return {"zeilen": zeilen, "spalten": spalten, "werte": werte}
