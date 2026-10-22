"""Kategorie-Scores und gewichteter Gesamtscore."""
from __future__ import annotations

from dataclasses import dataclass, field

from kern.konfig import KATEGORIEN


def kategorie_score(punkte_liste) -> float | None:
    """Durchschnitt der vorhandenen Punkte (0–10). Fehlende Kennzahlen werden ausgelassen."""
    werte = [p for p in punkte_liste if p is not None]
    if not werte:
        return None
    return sum(werte) / len(werte)


def einschaetzung_score(f1, f2, f3, f4) -> float:
    return (f1 + f2 + f3 + f4) / 4.0


def normierte_gewichte(gewichte: dict[str, float], aktiv: dict[str, bool]) -> dict[str, float]:
    """Gewichte der eingeschalteten Kategorien, normiert auf Summe 1."""
    roh = {k: max(float(gewichte.get(k, 0)), 0.0) if aktiv.get(k, True) else 0.0 for k in KATEGORIEN}
    summe = sum(roh.values())
    if summe <= 0:
        return {k: 0.0 for k in KATEGORIEN}
    return {k: v / summe for k, v in roh.items()}


@dataclass
class Gesamt:
    score: float | None                 # 0–100
    unvollstaendig: bool                # eine eingeschaltete Kategorie A–D fehlt
    einschaetzung_offen: bool           # Kategorie E noch nicht ausgefüllt
    fehlende: list[str] = field(default_factory=list)
    verwendete_gewichte: dict[str, float] = field(default_factory=dict)   # nach Hochrechnung, Summe 1
    beitraege: dict[str, float] = field(default_factory=dict)             # Punkte am Gesamtscore (0–100)


def gesamtscore(kat_scores: dict[str, float | None], gewichte: dict[str, float], aktiv: dict[str, bool]) -> Gesamt:
    """Gewichteter Durchschnitt der Kategorien, skaliert auf 0–100.

    Fehlende Kategorien werden ausgelassen und die übrigen Gewichte hochgerechnet.
    """
    norm = normierte_gewichte(gewichte, aktiv)
    beteiligt = {k: w for k, w in norm.items() if w > 0}
    vorhanden = {k: w for k, w in beteiligt.items() if kat_scores.get(k) is not None}
    fehlende = [k for k in beteiligt if k not in vorhanden]
    offen = "E" in fehlende
    unvollstaendig = any(k != "E" for k in fehlende)
    summe = sum(vorhanden.values())
    if summe <= 0:
        return Gesamt(None, unvollstaendig, offen, fehlende)
    verwendet = {k: w / summe for k, w in vorhanden.items()}
    beitraege = {k: kat_scores[k] * 10 * w for k, w in verwendet.items()}
    return Gesamt(sum(beitraege.values()), unvollstaendig, offen, fehlende, verwendet, beitraege)
