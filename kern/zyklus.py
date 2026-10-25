"""Zyklusuhr und Sektorfaktoren (antizyklisch).

Für jeden Indikator:
  Niveau   = Abstand des aktuellen Werts vom 10-Jahres-Durchschnitt in Standardabweichungen
  Richtung = Veränderung der letzten 6 Monate, ebenfalls in Standardabweichungen
Je Sektor werden die Indikatoren gewichtet gemittelt (Vorzeichen so, dass + = gut für den Sektor).
Aus Niveau und Richtung folgt die Phase und daraus der Grundfaktor; dazu kommt ein
Bewertungs-Bonus (Sektor-KGV und ETF-Kurs im Vergleich zur eigenen Geschichte).

Dieses Modul lädt nichts aus dem Internet und ist deshalb einzeln testbar.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from kern.format import prozent, zahl

MIN_MONATE = 36


# ---------------------------------------------------------------------
# Zeitreihen aufbereiten
# ---------------------------------------------------------------------

def monatlich(reihe: pd.Series) -> pd.Series:
    """Tages-, Wochen- oder Quartalswerte auf Monatswerte (Monatsdurchschnitt) bringen."""
    reihe = reihe.dropna()
    if reihe.empty:
        return reihe
    m = reihe.resample("ME").mean().dropna()
    return m


def umrechnen(reihe: pd.Series, art: str) -> pd.Series:
    """'niveau' = unverändert, 'jahresrate' = Veränderung zum Vorjahresmonat in %."""
    if art == "jahresrate":
        vorjahr = reihe.shift(12)
        return ((reihe / vorjahr - 1) * 100).replace([np.inf, -np.inf], np.nan).dropna()
    return reihe


@dataclass
class IndikatorStand:
    id: str
    name: str
    wert: float | None = None          # aktueller (umgerechneter) Wert
    einheit: str = ""
    datum: str = ""
    z_niveau: float | None = None      # + = über dem 10-Jahres-Schnitt
    z_richtung: float | None = None    # + = steigt
    grund: str | None = None


def indikator_auswerten(id_: str, name: str, reihe: pd.Series, jahre: int = 10, monate: int = 6,
                        einheit: str = "", heute: pd.Timestamp | None = None,
                        max_alter_monate: int = 6) -> IndikatorStand:
    st = IndikatorStand(id_, name, einheit=einheit)
    reihe = reihe.dropna()
    if len(reihe) < MIN_MONATE:
        st.grund = f"zu wenig Daten ({len(reihe)} Monate)"
        return st
    hist = reihe.iloc[-jahre * 12:]
    std = float(hist.std())
    st.wert, st.datum = float(hist.iloc[-1]), hist.index[-1].date().isoformat()
    heute = heute if heute is not None else pd.Timestamp.today()
    if (heute - hist.index[-1]).days > max_alter_monate * 31:
        st.grund = f"veraltet – letzter Wert vom {hist.index[-1]:%m/%Y}, wird nicht verwendet"
        return st
    if std == 0 or math.isnan(std):
        st.grund = "keine Schwankung"
        return st
    st.z_niveau = (st.wert - float(hist.mean())) / std
    diff = (reihe - reihe.shift(monate)).dropna().iloc[-jahre * 12:]
    std_diff = float(diff.std())
    if len(diff) >= 12 and std_diff > 0:
        st.z_richtung = float(diff.iloc[-1]) / std_diff
    return st


# ---------------------------------------------------------------------
# Bewertung eines Sektors
# ---------------------------------------------------------------------

def etf_trendabweichung(kurse: pd.Series, jahre: int = 10) -> float | None:
    """Abweichung des letzten Kurses vom log-linearen Trend der letzten ``jahre`` Jahre, in %."""
    if kurse is None or kurse.empty:
        return None
    w = kurse.dropna().resample("W").last().dropna()
    w = w.iloc[-jahre * 52:]
    if len(w) < 3 * 52:
        return None
    y = np.log(w.values.astype(float))
    x = np.arange(len(y), dtype=float)
    steigung, achse = np.polyfit(x, y, 1)
    return float((math.exp(y[-1] - (achse + steigung * x[-1])) - 1) * 100)


def kgv_perzentil(aktuell: float | None, historie: list[float]) -> float | None:
    """Anteil der historischen Werte, die unter dem aktuellen KGV liegen (0 = billigst, 1 = teuerst)."""
    werte = [h for h in historie if h is not None and h > 0]
    if aktuell is None or aktuell <= 0 or len(werte) < 4:
        return None
    return sum(1 for h in werte if h < aktuell) / len(werte)


def bewertungsbonus(kgv_aktuell, kgv_historie, etf_abweichung, max_bonus: float, etf_spanne: float):
    """Bonus (+ = günstig) und Erklärungstexte."""
    signale, texte = [], []
    p = kgv_perzentil(kgv_aktuell, kgv_historie)
    if p is not None:
        signale.append((0.5 - p) * 2)
        texte.append(f"Sektor-KGV {zahl(kgv_aktuell, 1)} – höher als in {prozent(p * 100, 0)} der letzten "
                     f"{len([h for h in kgv_historie if h])} Jahre")
    if etf_abweichung is not None:
        signale.append(-max(-1.0, min(1.0, etf_abweichung / etf_spanne)))
        texte.append(f"ETF-Kurs {prozent(etf_abweichung, 0)} {'über' if etf_abweichung >= 0 else 'unter'} "
                     f"dem 10-Jahres-Trend")
    if not signale:
        return 0.0, ["keine Bewertungsdaten"]
    return max_bonus * sum(signale) / len(signale), texte


# ---------------------------------------------------------------------
# Sektor
# ---------------------------------------------------------------------

@dataclass
class SektorStand:
    sektor: str
    niveau: float | None = None
    richtung: float | None = None
    phase: str = "neutral"
    grundfaktor: float = 1.0
    bonus: float = 0.0
    faktor: float = 1.0
    indikatoren: list[dict] = field(default_factory=list)   # je Indikator: Werte + Wirkung
    bewertung: list[str] = field(default_factory=list)
    kgv: float | None = None
    beta: float | None = None
    etf: str = ""
    etf_abweichung: float | None = None
    hinweis: str = ""

    def als_dict(self) -> dict:
        return asdict(self)


def phase_bestimmen(niveau: float, richtung: float, neutral_zone: float) -> str:
    if abs(niveau) < neutral_zone and abs(richtung) < neutral_zone:
        return "neutral"
    if niveau < 0:
        return "erholung" if richtung > 0 else "abschwung"
    return "aufschwung" if richtung > 0 else "boom"


def sektor_auswerten(sektor: str, sektor_cfg: dict, staende: dict[str, IndikatorStand], cfg: dict,
                     kgv: float | None = None, kgv_historie: list[float] | None = None,
                     beta: float | None = None, etf_abweichung: float | None = None) -> SektorStand:
    s = SektorStand(sektor, kgv=kgv, beta=beta, etf=sektor_cfg.get("etf", ""), etf_abweichung=etf_abweichung)
    summe_n = summe_r = gew_n = gew_r = 0.0
    for eintrag in sektor_cfg.get("indikatoren", []):
        st = staende.get(eintrag["id"])
        vorzeichen = 1.0 if eintrag.get("gut_wenn", "hoch") == "hoch" else -1.0
        gewicht = float(eintrag.get("gewicht", 1.0))
        zeile = {"id": eintrag["id"], "name": st.name if st else eintrag["id"], "gut_wenn": eintrag.get("gut_wenn", "hoch"),
                 "gewicht": gewicht, "wert": None, "datum": "", "niveau": None, "richtung": None,
                 "grund": None if st else "nicht verfügbar"}
        if st:
            zeile.update(wert=st.wert, datum=st.datum, grund=st.grund)
            if st.z_niveau is not None:
                zeile["niveau"] = vorzeichen * st.z_niveau
                summe_n += gewicht * zeile["niveau"]
                gew_n += gewicht
            if st.z_richtung is not None:
                zeile["richtung"] = vorzeichen * st.z_richtung
                summe_r += gewicht * zeile["richtung"]
                gew_r += gewicht
        s.indikatoren.append(zeile)

    phasen = cfg["phasen"]
    if gew_n > 0 and gew_r > 0:
        s.niveau, s.richtung = summe_n / gew_n, summe_r / gew_r
        s.phase = phase_bestimmen(s.niveau, s.richtung, float(cfg.get("neutral_zone", 0.25)))
    else:
        s.hinweis = "keine Makrodaten – Phase neutral"
    s.grundfaktor = float(phasen[s.phase]["faktor"])
    b = cfg.get("bewertung", {})
    s.bonus, s.bewertung = bewertungsbonus(kgv, kgv_historie or [], etf_abweichung,
                                           float(b.get("max_bonus", 0.10)), float(b.get("etf_spanne", 30)))
    roh = s.grundfaktor + s.bonus
    s.faktor = min(max(roh, float(cfg.get("faktor_min", 0.7))), float(cfg.get("faktor_max", 1.3)))
    return s


def faktor_text(s: dict, cfg: dict) -> str:
    """Kurzbegründung, z. B. 'Erholung 1,25 + Bewertung +0,04 = 1,29'."""
    name = cfg["phasen"][s["phase"]]["name"]
    teile = f"{name} {zahl(s['grundfaktor'], 2)} {'+' if s['bonus'] >= 0 else '–'} Bewertung {zahl(abs(s['bonus']), 2)}"
    roh = s["grundfaktor"] + s["bonus"]
    if abs(roh - s["faktor"]) > 1e-9:
        teile += f" (begrenzt auf {zahl(s['faktor'], 2)})"
    return f"{teile} = {zahl(s['faktor'], 2)}"
