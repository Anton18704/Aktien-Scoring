"""Umrechnung eines Rohwerts in 0–10 Punkte durch lineare Interpolation."""
from __future__ import annotations

import math


def punkte(wert: float | None, zehn: float, fuenf: float, null: float) -> float | None:
    """Liefert 0–10 Punkte.

    - Am Wert für 10 Punkte und darüber hinaus gibt es 10.
    - Am Wert für 0 Punkte und darüber hinaus gibt es 0.
    - Dazwischen linear, mit einem Knick beim Wert für 5 Punkte.
    Ist ``zehn`` größer als ``null``, gilt "höher ist besser", sonst umgekehrt.
    """
    if wert is None or (isinstance(wert, float) and math.isnan(wert)):
        return None
    zehn, fuenf, null = float(zehn), float(fuenf), float(null)
    # Auf "höher ist besser" umdrehen, damit nur ein Rechenweg nötig ist.
    if zehn < null:
        wert, zehn, fuenf, null = -wert, -zehn, -fuenf, -null
    if wert >= zehn:
        return 10.0
    if wert <= null:
        return 0.0
    if wert >= fuenf:
        return 5.0 + 5.0 * (wert - fuenf) / (zehn - fuenf)
    return 5.0 * (wert - null) / (fuenf - null)


def punkte_fuer(schluessel: str, wert: float | None, fixpunkte: float | None, schwellen: dict) -> float | None:
    """Punkte einer Kennzahl nach den aktuellen Schwellenwerten.

    ``fixpunkte`` ist für Sonderfälle wie "Nettocash = 10 Punkte" gesetzt und hat Vorrang.
    """
    if fixpunkte is not None:
        return float(fixpunkte)
    k = schwellen["kennzahlen"][schluessel]
    return punkte(wert, k["zehn"], k["fuenf"], k["null"])
