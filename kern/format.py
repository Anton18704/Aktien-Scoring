"""Zahlen im deutschen Format anzeigen."""
from __future__ import annotations


def zahl(v: float | None, nachkomma: int = 1) -> str:
    if v is None:
        return "–"
    s = f"{v:,.{nachkomma}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def betrag(v: float | None, waehrung: str = "") -> str:
    """z. B. 99580000000 -> '99,58 Mrd. USD'"""
    if v is None:
        return "–"
    a = abs(v)
    if a >= 1e9:
        s = f"{zahl(v / 1e9, 2)} Mrd."
    elif a >= 1e6:
        s = f"{zahl(v / 1e6, 1)} Mio."
    else:
        s = zahl(v, 0)
    return f"{s} {waehrung}".strip()


def prozent(v: float | None, nachkomma: int = 1) -> str:
    return "–" if v is None else f"{zahl(v, nachkomma)} %"
