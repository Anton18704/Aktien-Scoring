import pytest

from kern.konfig import lade_schwellen
from kern.punkte import punkte, punkte_fuer


class TestHoeherIstBesser:
    # FCF-Rendite: 7 / 5,5 / 4
    def test_an_den_schwellen(self):
        assert punkte(7.0, 7, 5.5, 4) == 10
        assert punkte(5.5, 7, 5.5, 4) == 5
        assert punkte(4.0, 7, 5.5, 4) == 0

    def test_darueber_und_darunter_begrenzt(self):
        assert punkte(25.0, 7, 5.5, 4) == 10
        assert punkte(-3.0, 7, 5.5, 4) == 0

    def test_linear_dazwischen(self):
        assert punkte(6.25, 7, 5.5, 4) == pytest.approx(7.5)
        assert punkte(4.75, 7, 5.5, 4) == pytest.approx(2.5)
        assert punkte(5.0, 7, 5.5, 4) == pytest.approx(10 / 3)


class TestNiedrigerIstBesser:
    # Max. Kursrückgang: 30 / 40 / 50
    def test_an_den_schwellen(self):
        assert punkte(30, 30, 40, 50) == 10
        assert punkte(40, 30, 40, 50) == 5
        assert punkte(50, 30, 40, 50) == 0

    def test_darueber_und_darunter_begrenzt(self):
        assert punkte(10, 30, 40, 50) == 10
        assert punkte(80, 30, 40, 50) == 0

    def test_linear_dazwischen(self):
        assert punkte(35, 30, 40, 50) == pytest.approx(7.5)
        assert punkte(45, 30, 40, 50) == pytest.approx(2.5)

    def test_negative_schwellen(self):
        # EV/EBIT-Abweichung: -20 / 0 / +20
        assert punkte(-20, -20, 0, 20) == 10
        assert punkte(-10, -20, 0, 20) == pytest.approx(7.5)
        assert punkte(0, -20, 0, 20) == 5
        assert punkte(30, -20, 0, 20) == 0


def test_fuenf_nicht_in_der_mitte():
    # Knick bei 5 Punkten wird eingehalten, auch wenn "fuenf" nicht genau in der Mitte liegt
    assert punkte(8, 10, 8, 0) == 5
    assert punkte(4, 10, 8, 0) == pytest.approx(2.5)
    assert punkte(9, 10, 8, 0) == pytest.approx(7.5)


def test_fehlender_wert():
    assert punkte(None, 7, 5.5, 4) is None
    assert punkte(float("nan"), 7, 5.5, 4) is None


def test_fixpunkte_haben_vorrang():
    s = lade_schwellen()
    assert punkte_fuer("nettoverschuldung_ebitda", 5.0, 10.0, s) == 10
    assert punkte_fuer("nettoverschuldung_ebitda", 5.0, None, s) == 0


def test_alle_kennzahlen_der_konfiguration():
    s = lade_schwellen()
    assert len(s["kennzahlen"]) == 14
    for k in s["kennzahlen"].values():
        assert punkte(k["zehn"], k["zehn"], k["fuenf"], k["null"]) == 10
        assert punkte(k["fuenf"], k["zehn"], k["fuenf"], k["null"]) == 5
        assert punkte(k["null"], k["zehn"], k["fuenf"], k["null"]) == 0
