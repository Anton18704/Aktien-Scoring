"""DCF-Modell mit Bear-, Base- und Bull-Szenario, Reverse DCF und Empfindlichkeitstabelle.

Zweistufig: In den ersten Jahren wächst der Free Cashflow mit dem Szenario-Wachstum,
danach sinkt das Wachstum gleichmäßig auf das langfristige Wachstum. Nach dem
letzten Prognosejahr folgt ein Endwert (Gordon-Modell, Branchen-Multiple oder
der Durchschnitt aus beiden).

Gerechnet wird mit dem Free Cashflow an die Aktionäre (nach Zinsen, nach
Aktienvergütung), abgezinst mit den Eigenkapitalkosten. Schulden sind über die
gezahlten Zinsen bereits berücksichtigt; vorhandenes Nettocash wird addiert.

Alle Werte in Prozent werden als Prozentzahl übergeben (4.5 = 4,5 %).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from kern.format import betrag, prozent, zahl

SZENARIEN = ("bear", "base", "bull")


@dataclass
class DcfEingaben:
    """Was bei einer Analyse aus den Abschlüssen gesichert wird (als JSON in der Datenbank)."""
    fcf_ttm: float | None = None
    fcf_jahre: list[float] = field(default_factory=list)   # die letzten 3 Geschäftsjahre
    wachstum: float | None = None                          # erwartetes Wachstum (bereits begrenzt), %
    wachstum_text: str = ""
    aktien: float | None = None
    kurs: float | None = None
    nettocash: float = 0.0                                 # Cash – Finanzschulden (negativ = Nettoschulden)
    waehrung: str = "USD"
    datenstand: str = ""
    quelle: str = ""
    zins: float | None = None                              # risikofreier Zins, %
    zins_datum: str = ""
    zins_quelle: str = ""
    grund: str | None = None                               # gesetzt, wenn kein DCF möglich ist

    def als_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def aus_dict(cls, d: dict) -> "DcfEingaben":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------
# Bausteine
# ---------------------------------------------------------------------

def start_fcf(e: DcfEingaben, art: str) -> float | None:
    werte = [w for w in [e.fcf_ttm, *e.fcf_jahre] if w is not None]
    if not werte:
        return None
    if art == "ttm":
        return e.fcf_ttm if e.fcf_ttm is not None else sum(werte) / len(werte)
    if art == "minimum":
        return min(werte)
    return sum(werte) / len(werte)


def wachstumspfad(g1: float, g_lang: float, jahre: int = 10, phase: int = 5) -> list[float]:
    """Wachstum je Jahr: ``phase`` Jahre lang g1, danach gleichmäßig sinkend bis g_lang."""
    pfad = []
    for t in range(1, jahre + 1):
        if t <= phase:
            pfad.append(g1)
        else:
            pfad.append(g1 + (g_lang - g1) * (t - phase) / (jahre - phase))
    return pfad


@dataclass
class SzenarioErgebnis:
    name: str
    wachstum: float
    wachstum_manuell: bool
    langfr_wachstum: float
    abzinsung: float
    exit_multiple: float
    start_fcf: float | None
    start_art: str
    fairer_wert: float | None = None      # je Aktie
    eigenkapitalwert: float | None = None
    endwert_anteil: float | None = None   # Anteil des Endwerts am Unternehmenswert, %
    endwert_methode: str = ""
    hinweis: str = ""


def unternehmenswert(start: float, g1: float, g_lang: float, r: float, multiple: float, cfg: dict):
    """Barwert der Free Cashflows + Endwert. Liefert (Wert, Endwert-Anteil %, verwendete Methode)."""
    jahre, phase = int(cfg.get("prognosejahre", 10)), int(cfg.get("wachstumsphase", 5))
    fcf, barwert = start, 0.0
    for t, g in enumerate(wachstumspfad(g1, g_lang, jahre, phase), start=1):
        fcf *= 1 + g / 100
        barwert += fcf / (1 + r / 100) ** t
    methode = cfg.get("endwert_methode", "durchschnitt")
    gordon = None
    if r - g_lang >= float(cfg.get("mindestabstand_gordon", 2.0)):
        gordon = fcf * (1 + g_lang / 100) / ((r - g_lang) / 100)
    mult = fcf * multiple
    if methode == "gordon" and gordon is not None:
        endwert, verwendet = gordon, "Gordon"
    elif methode == "durchschnitt" and gordon is not None:
        endwert, verwendet = (gordon + mult) / 2, "Ø Gordon/Multiple"
    else:
        endwert, verwendet = mult, "Multiple" + (" (Gordon instabil)" if methode != "multiple" else "")
    endwert_bar = endwert / (1 + r / 100) ** jahre
    gesamt = barwert + endwert_bar
    anteil = endwert_bar / gesamt * 100 if gesamt > 0 else None
    return gesamt, anteil, verwendet


def _je_aktie(wert: float, e: DcfEingaben) -> float:
    return (wert + max(e.nettocash, 0.0)) / e.aktien


def abzinsungssatz(e: DcfEingaben, cfg: dict, branche: dict) -> float:
    return float(e.zins) + float(cfg["marktrisikopraemie"]) + float(branche.get("zuschlag", 0.0))


def branchenwerte(cfg: dict, sektor: str | None) -> tuple[str, dict]:
    branchen = cfg.get("branchen", {})
    if sektor in branchen:
        return sektor, branchen[sektor]
    return "unbekannt", branchen.get("unbekannt", {"zuschlag": 0.5, "exit_multiple": 15})


def szenario_wachstum(name: str, g_basis: float, sz: dict, wachstum_min: float, wachstum_max: float) -> float:
    """Automatisches Szenario-Wachstum: Basiswachstum + Abstand, Bear nicht unter dem Minimum."""
    g = g_basis + float(sz.get("wachstum_delta", 0.0))
    if name == "bear":
        return max(g, wachstum_min)
    if name == "bull":
        return min(g, wachstum_max + float(sz.get("wachstum_delta", 0.0)))
    return g


# ---------------------------------------------------------------------
# Gesamtbewertung
# ---------------------------------------------------------------------

@dataclass
class DcfErgebnis:
    grund: str | None = None
    sektor: str = ""
    abzinsung_basis: float | None = None
    szenarien: dict[str, SzenarioErgebnis] = field(default_factory=dict)
    gewichte: dict[str, float] = field(default_factory=dict)
    fairer_wert: float | None = None          # gewichtet, je Aktie
    kurs: float | None = None
    sicherheitsmarge: float | None = None     # (fair – Kurs) ÷ fair, %
    bear_abstand: float | None = None         # (Bear – Kurs) ÷ Kurs, %
    eingepreistes_wachstum: float | None = None
    eingepreist_text: str = ""
    empfindlichkeit: dict = field(default_factory=dict)   # {"zeilen": [r], "spalten": [g], "werte": [[...]]}
    manuell: bool = False


def bewerten(e: DcfEingaben, sektor: str | None, cfg: dict, wachstum_min: float = -5.0,
             wachstum_max: float = 12.0, manuell: dict | None = None) -> DcfErgebnis:
    """Rechnet alle drei Szenarien. ``manuell`` = {"bear": %, "base": %, "bull": %} (None = automatisch)."""
    erg = DcfErgebnis(kurs=e.kurs)
    if e.grund:
        erg.grund = e.grund
        return erg
    if not e.aktien or e.aktien <= 0 or not e.kurs:
        erg.grund = "Aktienanzahl oder Kurs fehlt"
        return erg
    if e.zins is None:
        erg.grund = "kein risikofreier Zins verfügbar"
        return erg
    if e.wachstum is None:
        erg.grund = "kein erwartetes Wachstum berechenbar"
        return erg
    erg.sektor, branche = branchenwerte(cfg, sektor)
    erg.abzinsung_basis = abzinsungssatz(e, cfg, branche)
    manuell = manuell or {}
    erg.manuell = any(manuell.get(n) is not None for n in SZENARIEN)

    for name in SZENARIEN:
        sz = cfg["szenarien"][name]
        g_auto = szenario_wachstum(name, e.wachstum, sz, wachstum_min, wachstum_max)
        g = manuell.get(name) if manuell.get(name) is not None else g_auto
        art = sz.get("start_fcf", "durchschnitt")
        se = SzenarioErgebnis(
            name=sz.get("name", name), wachstum=float(g), wachstum_manuell=manuell.get(name) is not None,
            langfr_wachstum=float(sz["langfr_wachstum"]), abzinsung=erg.abzinsung_basis + float(sz["abzinsung_delta"]),
            exit_multiple=float(branche["exit_multiple"]) * float(sz["multiple_faktor"]),
            start_fcf=start_fcf(e, art), start_art=art)
        if se.start_fcf is None:
            se.hinweis = "kein Free Cashflow"
        elif se.start_fcf <= 0:
            # Ohne positiven Cashflow ist nur das Nettocash etwas wert (vorsichtige Annahme)
            se.fairer_wert, se.eigenkapitalwert = _je_aktie(0.0, e), 0.0
            se.hinweis = "Start-FCF nicht positiv → nur Nettocash angesetzt"
        else:
            wert, anteil, methode = unternehmenswert(se.start_fcf, se.wachstum, se.langfr_wachstum,
                                                     se.abzinsung, se.exit_multiple, cfg)
            se.eigenkapitalwert, se.endwert_anteil, se.endwert_methode = wert, anteil, methode
            se.fairer_wert = _je_aktie(wert, e)
        erg.szenarien[name] = se

    base = erg.szenarien["base"]
    if base.fairer_wert is None or base.start_fcf is None or base.start_fcf <= 0:
        erg.grund = "Free Cashflow nicht positiv – DCF nicht sinnvoll"
        return erg
    gueltig = {n: float(cfg["szenarien"][n]["gewicht"]) for n, s in erg.szenarien.items() if s.fairer_wert is not None}
    summe = sum(gueltig.values())
    erg.gewichte = {n: w / summe for n, w in gueltig.items()}
    erg.fairer_wert = sum(erg.szenarien[n].fairer_wert * w for n, w in erg.gewichte.items())
    if erg.fairer_wert > 0:
        erg.sicherheitsmarge = (erg.fairer_wert - e.kurs) / erg.fairer_wert * 100
    else:
        erg.sicherheitsmarge = -100.0
    bear = erg.szenarien["bear"]
    if bear.fairer_wert is not None:
        erg.bear_abstand = (bear.fairer_wert - e.kurs) / e.kurs * 100

    erg.eingepreistes_wachstum, erg.eingepreist_text = eingepreistes_wachstum(e, base, cfg)
    erg.empfindlichkeit = empfindlichkeit(e, base, cfg)
    return erg


def _base_wert(e: DcfEingaben, base: SzenarioErgebnis, cfg: dict, g1: float, r: float | None = None) -> float:
    wert, _, _ = unternehmenswert(base.start_fcf, g1, base.langfr_wachstum,
                                  base.abzinsung if r is None else r, base.exit_multiple, cfg)
    return _je_aktie(wert, e)


def eingepreistes_wachstum(e: DcfEingaben, base: SzenarioErgebnis, cfg: dict,
                           unten: float = -30.0, oben: float = 60.0) -> tuple[float | None, str]:
    """Reverse DCF: Welches Wachstum (Jahre 1–5) rechtfertigt den heutigen Kurs im Base-Szenario?"""
    if _base_wert(e, base, cfg, unten) > e.kurs:
        return None, f"Kurs liegt sogar unter dem Wert bei {zahl(unten, 0)} % Wachstum pro Jahr"
    if _base_wert(e, base, cfg, oben) < e.kurs:
        return None, f"Kurs unterstellt mehr als {zahl(oben, 0)} % Wachstum pro Jahr"
    for _ in range(60):
        mitte = (unten + oben) / 2
        if _base_wert(e, base, cfg, mitte) < e.kurs:
            unten = mitte
        else:
            oben = mitte
    g = (unten + oben) / 2
    return g, f"Der Kurs unterstellt rund {prozent(g)} FCF-Wachstum pro Jahr in den nächsten 5 Jahren"


def empfindlichkeit(e: DcfEingaben, base: SzenarioErgebnis, cfg: dict) -> dict:
    """Fairer Wert (Base) bei verschiedenen Abzinsungssätzen (Zeilen) und Wachstumsraten (Spalten)."""
    zeilen = [base.abzinsung + d for d in (-1.0, -0.5, 0.0, 0.5, 1.0)]
    spalten = [base.wachstum + d for d in (-2.0, -1.0, 0.0, 1.0, 2.0)]
    werte = [[_base_wert(e, base, cfg, g, r) for g in spalten] for r in zeilen]
    return {"zeilen": zeilen, "spalten": spalten, "werte": werte}


def kurzbeschreibung(erg: DcfErgebnis, e: DcfEingaben) -> str:
    """Rechenweg in einer Zeile für die Kennzahlentabelle."""
    teile = [f"{s.name} {zahl(s.fairer_wert, 2)}" for s in erg.szenarien.values() if s.fairer_wert is not None]
    return (f"fairer Wert {zahl(erg.fairer_wert, 2)} {e.waehrung} (gewichtet; " + ", ".join(teile) +
            f") vs. Kurs {zahl(e.kurs, 2)}; Abzinsung Base {prozent(erg.abzinsung_basis)}, "
            f"Nettocash {betrag(e.nettocash, e.waehrung)}")
