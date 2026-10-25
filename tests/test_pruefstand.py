"""Tests für die Auswertung des Prüfstands (kern/pruefstand.py)."""
import numpy as np
import pandas as pd

from kern import pruefstand as ps

PHASEN = {"erholung": {"name": "Erholung", "faktor": 1.25}, "abschwung": {"name": "Abschwung", "faktor": 1.05},
          "neutral": {"name": "Neutral", "faktor": 1.0}, "aufschwung": {"name": "Aufschwung", "faktor": 0.9},
          "boom": {"name": "Boom/Wende", "faktor": 0.75}}


def beobachtungen(signal: float, seed=0):
    """Je Phase eine Rendite = signal × (Faktor – 1) × 20 + Rauschen."""
    rng = np.random.default_rng(seed)
    zeilen = []
    for m in pd.date_range("2010-01-31", periods=120, freq="ME"):
        for p, d in PHASEN.items():
            zeilen.append({"monat": m, "sektor": p, "phase": p, "faktor": d["faktor"],
                           "rel": signal * (d["faktor"] - 1) * 20 + rng.normal(0, 3)})
    return pd.DataFrame(zeilen)


def test_wirksame_regeln_bestehen():
    erg = ps.auswerten(beobachtungen(+1.0), PHASEN)
    assert erg["bestanden"] and erg["korrelation"] > 0.2
    assert erg["je_phase"]["erholung"]["mittel"] > erg["je_phase"]["boom"]["mittel"]


def test_falsch_herum_faellt_durch():
    erg = ps.auswerten(beobachtungen(-1.0), PHASEN)
    assert not erg["bestanden"]
    assert not any(p["ok"] for p in erg["pruefungen"])


def test_reines_rauschen_faellt_durch():
    erg = ps.auswerten(beobachtungen(0.0, seed=3), PHASEN)
    assert not erg["bestanden"]


def test_zu_wenig_daten():
    assert ps.auswerten(beobachtungen(1.0).head(10), PHASEN)["grund"]
