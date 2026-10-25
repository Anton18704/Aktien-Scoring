import pytest

from kern.gesamtscore import einschaetzung_score, gesamtscore, kategorie_score, normierte_gewichte

STANDARD = {"A": 25, "B": 20, "C": 15, "D": 20, "E": 20}
ALLE_AN = {k: True for k in "ABCDE"}


def test_kategorie_score_ist_durchschnitt():
    assert kategorie_score([10, 5, 0]) == 5
    assert kategorie_score([10, None, 6]) == 8       # fehlende Kennzahl wird ausgelassen
    assert kategorie_score([None, None]) is None


def test_einschaetzung():
    assert einschaetzung_score(10, 8, 6, 4) == 7


def test_gewichte_werden_normiert():
    n = normierte_gewichte({"A": 50, "B": 50, "C": 50, "D": 50, "E": 50}, ALLE_AN)
    assert all(v == pytest.approx(0.2) for v in n.values())
    n = normierte_gewichte(STANDARD, {**ALLE_AN, "E": False})
    assert n["E"] == 0
    assert n["A"] == pytest.approx(25 / 80)


def test_vollstaendiger_gesamtscore():
    g = gesamtscore({"A": 8, "B": 6, "C": 10, "D": 4, "E": 5}, STANDARD, ALLE_AN)
    erwartet = (8 * 25 + 6 * 20 + 10 * 15 + 4 * 20 + 5 * 20) / 100 * 10
    assert g.score == pytest.approx(erwartet)
    assert not g.unvollstaendig and not g.einschaetzung_offen
    assert sum(g.beitraege.values()) == pytest.approx(g.score)


def test_einschaetzung_offen_rechnet_ohne_e():
    g = gesamtscore({"A": 8, "B": 6, "C": 10, "D": 4, "E": None}, STANDARD, ALLE_AN)
    assert g.einschaetzung_offen
    assert not g.unvollstaendig
    assert g.score == pytest.approx((8 * 25 + 6 * 20 + 10 * 15 + 4 * 20) / 80 * 10)


def test_fehlende_kategorie_wird_hochgerechnet():
    g = gesamtscore({"A": 10, "B": None, "C": 10, "D": 10, "E": 10}, STANDARD, ALLE_AN)
    assert g.unvollstaendig
    assert g.fehlende == ["B"]
    assert g.score == pytest.approx(100)
    assert sum(g.verwendete_gewichte.values()) == pytest.approx(1)


def test_ausgeschaltete_kategorie_zaehlt_nicht_als_fehlend():
    g = gesamtscore({"A": 10, "B": None, "C": 0, "D": 0, "E": 0}, STANDARD, {**ALLE_AN, "B": False})
    assert not g.unvollstaendig
    assert g.score == pytest.approx(25 / 80 * 100)


def test_nichts_vorhanden():
    g = gesamtscore({k: None for k in "ABCDE"}, STANDARD, ALLE_AN)
    assert g.score is None


def test_ko_kategorien():
    g = gesamtscore({"A": 8, "B": 2.5, "C": 10, "D": 4, "E": None}, STANDARD, ALLE_AN, ko_schwelle=3)
    assert g.ko == ["B"]
    # ausgeschaltete Kategorien lösen keinen K.o. aus
    g = gesamtscore({"A": 8, "B": 2.5, "C": 10, "D": 4, "E": None}, STANDARD, {**ALLE_AN, "B": False}, ko_schwelle=3)
    assert g.ko == []
    # ohne Schwelle kein K.o.
    assert gesamtscore({"A": 0, "B": 0, "C": 0, "D": 0, "E": 0}, STANDARD, ALLE_AN).ko == []
