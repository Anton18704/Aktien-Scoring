"""Prüfstand: Hätten die Sektorfaktoren in der Vergangenheit bessere Entscheidungen gebracht?

Eingabe: je Sektor und Monat die damals berechnete Phase, der Faktor und die Rendite des
Sektor-ETFs in den folgenden Monaten relativ zum S&P 500. Ausgabe: Kennzahlen je Phase und ein
nachvollziehbares Urteil.

Bestanden, wenn alle drei Bedingungen erfüllt sind:
  1. Sektor-Monate mit Faktor über 1 schnitten im Schnitt besser ab als die mit Faktor unter 1
     – und zwar in BEIDEN Hälften des Zeitraums (sonst ist es Zufall/Regime-abhängig).
  2. Die Korrelation zwischen Faktor und späterer Rendite ist positiv (mindestens +0,05).
  3. Die Phase mit dem höchsten Faktor schnitt besser ab als die mit dem niedrigsten.
"""
from __future__ import annotations

import pandas as pd

MIN_KORRELATION = 0.05


def _gruppe(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"anzahl": 0, "mittel": None, "median": None, "treffer": None}
    return {"anzahl": int(len(df)), "mittel": float(df.rel.mean()), "median": float(df.rel.median()),
            "treffer": float((df.rel > 0).mean() * 100)}


def auswerten(beob: pd.DataFrame, phasen_cfg: dict) -> dict:
    """``beob`` braucht die Spalten monat, sektor, phase, faktor, rel (relative Rendite in %)."""
    beob = beob.dropna(subset=["rel", "faktor"])
    if len(beob) < 50:
        return {"grund": f"zu wenige Beobachtungen ({len(beob)})"}
    reihenfolge = sorted(phasen_cfg, key=lambda p: -float(phasen_cfg[p]["faktor"]))
    je_phase = {p: {**_gruppe(beob[beob.phase == p]), "faktor": float(phasen_cfg[p]["faktor"]),
                    "name": phasen_cfg[p]["name"]} for p in reihenfolge}
    gesamt_mittel = float(beob.rel.mean())
    korrelation = float(beob[["faktor", "rel"]].corr().iloc[0, 1])

    mitte = beob.monat.sort_values().iloc[len(beob) // 2]
    haelften = {}
    for name, teil in (("erste", beob[beob.monat < mitte]), ("zweite", beob[beob.monat >= mitte])):
        hoch, tief = teil[teil.faktor > 1.0].rel, teil[teil.faktor < 1.0].rel
        haelften[name] = {
            "von": teil.monat.min().strftime("%m/%Y"), "bis": teil.monat.max().strftime("%m/%Y"),
            "faktor_hoch": float(hoch.mean()) if len(hoch) else None,
            "faktor_tief": float(tief.mean()) if len(tief) else None,
        }
    def vorsprung(h):
        return None if h["faktor_hoch"] is None or h["faktor_tief"] is None else h["faktor_hoch"] - h["faktor_tief"]
    besetzt = [p for p in reihenfolge if je_phase[p]["anzahl"] >= 20]
    oben, unten = (besetzt[0], besetzt[-1]) if len(besetzt) >= 2 else (None, None)

    pruefungen = [
        ("Faktor > 1 schlägt Faktor < 1 in beiden Hälften",
         all(vorsprung(h) is not None and vorsprung(h) > 0 for h in haelften.values())),
        (f"Korrelation Faktor ↔ spätere Rendite mindestens +{MIN_KORRELATION:.2f}", korrelation >= MIN_KORRELATION),
        ("Phase mit höchstem Faktor besser als Phase mit niedrigstem",
         oben is not None and je_phase[oben]["mittel"] > je_phase[unten]["mittel"]),
    ]
    return {"grund": None, "anzahl": int(len(beob)), "von": beob.monat.min().strftime("%m/%Y"),
            "bis": beob.monat.max().strftime("%m/%Y"), "gesamt_mittel": gesamt_mittel,
            "korrelation": korrelation, "je_phase": je_phase, "haelften": haelften,
            "vorsprung": {k: vorsprung(h) for k, h in haelften.items()},
            "pruefungen": [{"text": t, "ok": bool(ok)} for t, ok in pruefungen],
            "bestanden": all(ok for _, ok in pruefungen)}
