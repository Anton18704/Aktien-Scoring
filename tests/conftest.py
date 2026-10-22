import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kern.kennzahlen import Finanzdaten, Wert  # noqa: E402


def w(wert, ende, quelle="test", start=None):
    return Wert(float(wert), ende if isinstance(ende, date) else date.fromisoformat(ende), quelle, start)


def jahresreihe(werte, erstes_jahr=2015):
    """[a, b, c] -> Werte zum 31.12. der aufeinanderfolgenden Jahre."""
    return [w(v, date(erstes_jahr + i, 12, 31)) for i, v in enumerate(werte)]


@pytest.fixture
def fd_leer():
    return Finanzdaten(waehrung="USD")


@pytest.fixture
def fd_basis():
    """Ein einfaches, vollständiges Unternehmen mit Bilanzstichtag 31.12.2025."""
    tag = date(2025, 12, 31)
    fd = Finanzdaten(waehrung="USD", kurs_waehrung="USD", kurs_quelle="test-kurse")
    fd.ttm = {
        "umsatz": w(1000, tag), "ebit": w(200, tag), "ocf": w(180, tag), "capex": w(30, tag),
        "abschreibungen": w(50, tag), "zinsaufwand": w(20, tag), "nettogewinn": w(150, tag),
        "dividenden": w(40, tag), "rueckkaeufe": w(30, tag), "aktienausgabe": w(10, tag),
    }
    fd.bilanz = {
        "bilanzsumme": [w(2000, tag)], "umlaufvermoegen": [w(600, tag)], "kurzfr_verbindlichkeiten": [w(400, tag)],
        "verbindlichkeiten": [w(1200, tag)], "eigenkapital": [w(800, tag)], "gewinnruecklagen": [w(500, tag)],
        "cash": [w(100, tag)], "kurzfr_wertpapiere": [w(50, tag)],
        "ltd_langfristig": [w(400, tag)], "ltd_kurzfristig": [w(50, tag)], "commercial_paper": [w(25, tag)],
    }
    fd.aktien_aktuell = w(100, tag)
    fd.kurs_aktuell = w(20, tag)   # Marktkap. = 2000
    return fd
