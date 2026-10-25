"""Tests für Zyklusuhr, Sektorfaktoren und Damodaran-Branchenwerte im DCF."""
import numpy as np
import pandas as pd
import pytest

from kern import dcf, zyklus

CFG = {
    "faktor_min": 0.7, "faktor_max": 1.3, "neutral_zone": 0.25,
    "phasen": {"erholung": {"name": "Erholung", "faktor": 1.25}, "abschwung": {"name": "Abschwung", "faktor": 1.05},
               "aufschwung": {"name": "Aufschwung", "faktor": 0.90}, "boom": {"name": "Boom/Wende", "faktor": 0.75},
               "neutral": {"name": "Neutral", "faktor": 1.0}},
    "bewertung": {"max_bonus": 0.10, "etf_spanne": 30},
}


def monatsreihe(werte, ende="2026-09-30"):
    return pd.Series(werte, index=pd.date_range(end=ende, periods=len(werte), freq="ME"), dtype=float)


def test_phasen():
    assert zyklus.phase_bestimmen(-1.0, 0.8, 0.25) == "erholung"
    assert zyklus.phase_bestimmen(-1.0, -0.8, 0.25) == "abschwung"
    assert zyklus.phase_bestimmen(1.0, 0.8, 0.25) == "aufschwung"
    assert zyklus.phase_bestimmen(1.0, -0.8, 0.25) == "boom"
    assert zyklus.phase_bestimmen(0.1, -0.1, 0.25) == "neutral"


def test_jahresrate_und_monatswerte():
    tage = pd.date_range("2020-01-01", "2021-12-31", freq="D")
    s = zyklus.monatlich(pd.Series(100.0, index=tage))
    assert len(s) == 24
    reihe = monatsreihe([100.0] * 12 + [110.0] * 12)
    assert zyklus.umrechnen(reihe, "jahresrate").iloc[-1] == pytest.approx(10.0)


def test_indikator_tief_und_steigend():
    """10 Jahre um 100 schwankend, zuletzt tief gefallen und wieder leicht steigend."""
    rng = np.random.default_rng(1)
    werte = list(100 + rng.normal(0, 2, 114)) + [92, 90, 88, 89, 90, 91]
    st = zyklus.indikator_auswerten("x", "Test", monatsreihe(werte))
    assert st.z_niveau < -1.0          # deutlich unter dem Durchschnitt
    st2 = zyklus.indikator_auswerten("x", "Test", monatsreihe(werte), monate=3)
    assert st2.z_richtung > 0          # in den letzten 3 Monaten steigend


def test_zu_kurze_reihe():
    st = zyklus.indikator_auswerten("x", "Test", monatsreihe([1.0] * 20))
    assert st.grund and st.z_niveau is None


def _stand(id_, niveau, richtung):
    return zyklus.IndikatorStand(id_, id_, wert=1.0, datum="2026-09-30", z_niveau=niveau, z_richtung=richtung)


def test_sektor_erholung_antizyklisch():
    """Schlechte, aber sich bessernde Daten → höchster Faktor."""
    sektor_cfg = {"etf": "XLE", "indikatoren": [{"id": "oel", "gut_wenn": "hoch", "gewicht": 2}]}
    s = zyklus.sektor_auswerten("Energie", sektor_cfg, {"oel": _stand("oel", -1.5, 1.0)}, CFG)
    assert s.phase == "erholung" and s.faktor == pytest.approx(1.25)


def test_gut_wenn_niedrig_dreht_das_vorzeichen():
    """Hoher, weiter steigender Hypothekenzins ist schlecht für Immobilien → Abschwung."""
    sektor_cfg = {"indikatoren": [{"id": "hypozins", "gut_wenn": "niedrig"}]}
    s = zyklus.sektor_auswerten("Immobilien", sektor_cfg, {"hypozins": _stand("hypozins", 1.2, 0.9)}, CFG)
    assert s.niveau == pytest.approx(-1.2) and s.richtung == pytest.approx(-0.9)
    assert s.phase == "abschwung"


def test_gewichtung_der_indikatoren():
    sektor_cfg = {"indikatoren": [{"id": "a", "gewicht": 3}, {"id": "b", "gewicht": 1}]}
    s = zyklus.sektor_auswerten("X", sektor_cfg, {"a": _stand("a", 1.0, 1.0), "b": _stand("b", -1.0, -1.0)}, CFG)
    assert s.niveau == pytest.approx(0.5) and s.richtung == pytest.approx(0.5)


def test_bewertungsbonus_und_begrenzung():
    sektor_cfg = {"indikatoren": [{"id": "oel"}]}
    # Erholung (1,25) + sehr günstiger Sektor (+0,10) = 1,35 → begrenzt auf 1,30
    s = zyklus.sektor_auswerten("Energie", sektor_cfg, {"oel": _stand("oel", -1.5, 1.0)}, CFG,
                                kgv=5, kgv_historie=[10, 12, 14, 16, 18], etf_abweichung=-40)
    assert s.bonus == pytest.approx(0.10)
    assert s.faktor == pytest.approx(1.30)
    assert "begrenzt" in zyklus.faktor_text(s.als_dict(), CFG)
    # Boom (0,75) + sehr teuer (–0,10) = 0,65 → begrenzt auf 0,70
    s = zyklus.sektor_auswerten("Energie", sektor_cfg, {"oel": _stand("oel", 1.5, -1.0)}, CFG,
                                kgv=30, kgv_historie=[10, 12, 14, 16, 18], etf_abweichung=40)
    assert s.faktor == pytest.approx(0.70)


def test_ohne_daten_neutral():
    s = zyklus.sektor_auswerten("X", {"indikatoren": [{"id": "fehlt"}]}, {}, CFG)
    assert s.phase == "neutral" and s.faktor == 1.0 and s.hinweis


def test_kgv_perzentil():
    assert zyklus.kgv_perzentil(15, [10, 12, 14, 16, 18, 20]) == pytest.approx(0.5)
    assert zyklus.kgv_perzentil(15, [10, 12]) is None      # zu wenig Historie


def test_etf_trendabweichung():
    tage = pd.bdate_range("2016-01-01", "2026-09-30")
    trend = pd.Series(100 * np.exp(np.linspace(0, 1, len(tage))), index=tage)
    assert zyklus.etf_trendabweichung(trend) == pytest.approx(0, abs=0.5)
    hoch = trend.copy()
    hoch.iloc[-30:] *= 1.2
    assert zyklus.etf_trendabweichung(hoch) > 15


def test_dcf_branchen_aus_damodaran():
    cfg = {"marktrisikopraemie": 4.0, "branchenwerte": "damodaran",
           "damodaran_grenzen": {"zuschlag_min": -1.5, "zuschlag_max": 2.5, "multiple_min": 8, "multiple_max": 25},
           "branchen": {"IT": {"zuschlag": 0.5, "exit_multiple": 22}, "unbekannt": {"zuschlag": 0.5, "exit_multiple": 15}}}
    sek = {"IT": {"beta": 1.25, "kgv": 40, "kgv_historie": {2020: 20, 2021: 22, 2022: 24}},
           "Versorger": {"beta": 0.4, "kgv": 20, "kgv_historie": {}}}
    neu = dcf.mit_damodaran(cfg, sek)
    assert neu["branchen"]["IT"]["zuschlag"] == pytest.approx(1.0)            # (1,25 – 1) × 4
    assert neu["branchen"]["IT"]["exit_multiple"] == pytest.approx(23)        # Median 20, 22, 24, 40
    assert neu["branchen"]["Versorger"]["zuschlag"] == pytest.approx(-1.5)   # (0,4 – 1) × 4 = –2,4 → begrenzt
    assert neu["branchen"]["Versorger"]["exit_multiple"] == 15                # zu wenig KGV-Jahre → Ersatzwert
    assert cfg["branchen"]["IT"]["zuschlag"] == 0.5                           # Original unverändert
    assert dcf.mit_damodaran({**cfg, "branchenwerte": "tabelle"}, sek) is not None
    assert dcf.mit_damodaran({**cfg, "branchenwerte": "tabelle"}, sek)["branchen"]["IT"]["zuschlag"] == 0.5


def test_echte_konfiguration_vollstaendig():
    from makro_sektoren import lade_makro_cfg
    cfg = lade_makro_cfg()
    assert len(cfg["sektoren"]) == 11
    for sektor, sc in cfg["sektoren"].items():
        for eintrag in sc["indikatoren"]:
            assert eintrag["id"] in cfg["indikatoren"], f"{sektor}: {eintrag['id']} unbekannt"
            assert eintrag.get("gut_wenn", "hoch") in ("hoch", "niedrig")
    for name in ("erholung", "abschwung", "aufschwung", "boom", "neutral"):
        assert name in cfg["phasen"]


def test_veralteter_indikator_wird_ausgelassen():
    """Wie der OECD-Frühindikator auf FRED: endet 2024 → nicht verwenden."""
    reihe = monatsreihe(list(range(60)), ende="2024-01-31")
    st = zyklus.indikator_auswerten("x", "Test", reihe, heute=pd.Timestamp("2026-10-25"))
    assert st.grund and "veraltet" in st.grund and st.z_niveau is None
    st = zyklus.indikator_auswerten("x", "Test", reihe, heute=pd.Timestamp("2024-03-15"))
    assert st.grund is None and st.z_niveau is not None
