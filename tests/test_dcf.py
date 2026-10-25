"""Tests für das DCF-Modell (kern/dcf.py)."""
import pytest

from kern import dcf
from kern.konfig import lade_dcf

CFG = {
    "marktrisikopraemie": 4.0, "prognosejahre": 10, "wachstumsphase": 5, "endwert_methode": "gordon",
    "mindestabstand_gordon": 2.0,
    "szenarien": {
        "bear": {"name": "Bear", "gewicht": 25, "wachstum_delta": -3, "langfr_wachstum": 2.0, "abzinsung_delta": 1.0,
                 "multiple_faktor": 0.75, "start_fcf": "minimum"},
        "base": {"name": "Base", "gewicht": 50, "wachstum_delta": 0, "langfr_wachstum": 2.0, "abzinsung_delta": 0.0,
                 "multiple_faktor": 1.0, "start_fcf": "durchschnitt"},
        "bull": {"name": "Bull", "gewicht": 25, "wachstum_delta": 2, "langfr_wachstum": 2.0, "abzinsung_delta": -0.5,
                 "multiple_faktor": 1.2, "start_fcf": "ttm"},
    },
    "branchen": {"Basiskonsum": {"zuschlag": 0.0, "exit_multiple": 20}, "unbekannt": {"zuschlag": 1.0, "exit_multiple": 15}},
}


def eingaben(**kw):
    basis = dict(fcf_ttm=100.0, fcf_jahre=[100.0, 100.0, 100.0], wachstum=2.0, aktien=10.0, kurs=100.0,
                 nettocash=0.0, zins=4.0)
    basis.update(kw)
    return dcf.DcfEingaben(**basis)


def test_wachstumspfad():
    pfad = dcf.wachstumspfad(10, 2, jahre=10, phase=5)
    assert pfad[:5] == [10] * 5
    assert pfad[5] == pytest.approx(8.4) and pfad[-1] == pytest.approx(2)


def test_ohne_wachstum_entspricht_gordon_formel():
    """Wachstum überall = langfristiges Wachstum → Wert = FCF × (1+g) ÷ (r – g) (klassische Gordon-Formel)."""
    wert, anteil, methode = dcf.unternehmenswert(100, 2, 2, 8, 20, CFG)
    assert wert == pytest.approx(100 * 1.02 / 0.06, rel=1e-9)
    assert methode == "Gordon" and 0 < anteil < 100


def test_endwert_durchschnitt_und_instabiles_gordon():
    cfg = {**CFG, "endwert_methode": "durchschnitt"}
    _, _, methode = dcf.unternehmenswert(100, 5, 2, 8, 20, cfg)
    assert methode == "Ø Gordon/Multiple"
    _, _, methode = dcf.unternehmenswert(100, 5, 3, 4, 20, cfg)      # r – g = 1 < 2 → nur Multiple
    assert "Gordon instabil" in methode


def test_start_fcf_arten():
    e = eingaben(fcf_ttm=120.0, fcf_jahre=[60.0, 90.0, 90.0])
    assert dcf.start_fcf(e, "ttm") == 120
    assert dcf.start_fcf(e, "minimum") == 60
    assert dcf.start_fcf(e, "durchschnitt") == pytest.approx(90)


def test_szenarien_geordnet_und_gewichtet():
    erg = dcf.bewerten(eingaben(), "Basiskonsum", CFG)
    bear, base, bull = (erg.szenarien[n].fairer_wert for n in ("bear", "base", "bull"))
    assert bear < base < bull
    assert erg.fairer_wert == pytest.approx(0.25 * bear + 0.5 * base + 0.25 * bull)
    assert erg.sicherheitsmarge == pytest.approx((erg.fairer_wert - 100) / erg.fairer_wert * 100)
    # Base mit r = 8 %, g = 2 % überall: 100 × 1,02 ÷ 0,06 = 1.700 → je Aktie 170
    assert base == pytest.approx(170)


def test_abzinsung_setzt_sich_zusammen():
    erg = dcf.bewerten(eingaben(), "Basiskonsum", CFG)
    assert erg.abzinsung_basis == pytest.approx(4.0 + 4.0 + 0.0)
    erg = dcf.bewerten(eingaben(), "gibt es nicht", CFG)
    assert erg.sektor == "unbekannt" and erg.abzinsung_basis == pytest.approx(9.0)


def test_nettocash_wird_addiert():
    ohne = dcf.bewerten(eingaben(), "Basiskonsum", CFG).szenarien["base"].fairer_wert
    mit = dcf.bewerten(eingaben(nettocash=500.0), "Basiskonsum", CFG).szenarien["base"].fairer_wert
    assert mit == pytest.approx(ohne + 50)
    schulden = dcf.bewerten(eingaben(nettocash=-500.0), "Basiskonsum", CFG).szenarien["base"].fairer_wert
    assert schulden == pytest.approx(ohne)   # Schulden stecken schon in den Zinsen (FCF nach Zinsen)


def test_manuelles_wachstum():
    auto = dcf.bewerten(eingaben(), "Basiskonsum", CFG)
    hand = dcf.bewerten(eingaben(), "Basiskonsum", CFG, manuell={"bear": None, "base": 8.0, "bull": None})
    assert hand.manuell and hand.szenarien["base"].wachstum == 8.0 and hand.szenarien["base"].wachstum_manuell
    assert hand.szenarien["bear"].wachstum == auto.szenarien["bear"].wachstum
    assert hand.szenarien["base"].fairer_wert > auto.szenarien["base"].fairer_wert


def test_bear_wachstum_nicht_unter_minimum():
    erg = dcf.bewerten(eingaben(wachstum=-4.0), "Basiskonsum", CFG, wachstum_min=-5.0)
    assert erg.szenarien["bear"].wachstum == -5.0


def test_reverse_dcf_trifft_den_kurs():
    e = eingaben()
    erg = dcf.bewerten(e, "Basiskonsum", CFG)
    base = erg.szenarien["base"]
    g = erg.eingepreistes_wachstum
    assert g is not None
    assert dcf._base_wert(e, base, CFG, g) == pytest.approx(e.kurs, rel=1e-6)
    assert g < base.wachstum   # Kurs 100 < fairer Wert 170 → weniger Wachstum eingepreist


def test_empfindlichkeit():
    erg = dcf.bewerten(eingaben(), "Basiskonsum", CFG)
    t = erg.empfindlichkeit
    assert len(t["werte"]) == 5 and len(t["werte"][0]) == 5
    assert t["werte"][2][2] == pytest.approx(erg.szenarien["base"].fairer_wert)
    assert t["werte"][0][2] > t["werte"][4][2]        # niedrigere Abzinsung → höherer Wert
    assert t["werte"][2][4] > t["werte"][2][0]        # mehr Wachstum → höherer Wert


def test_negativer_fcf():
    erg = dcf.bewerten(eingaben(fcf_ttm=-50.0, fcf_jahre=[-20.0, -30.0, -10.0]), "Basiskonsum", CFG)
    assert erg.grund and "nicht positiv" in erg.grund
    # Bear mit negativem Minimum, Base positiv: Bear setzt nur Nettocash an
    erg = dcf.bewerten(eingaben(fcf_jahre=[-50.0, 100.0, 100.0], nettocash=100.0), "Basiskonsum", CFG)
    assert erg.szenarien["bear"].fairer_wert == pytest.approx(10.0)
    assert erg.grund is None


def test_fehlende_eingaben():
    assert dcf.bewerten(eingaben(grund="kein Kurs"), "IT", CFG).grund == "kein Kurs"
    assert dcf.bewerten(eingaben(zins=None), "IT", CFG).grund


def test_echte_konfiguration_ist_vollstaendig():
    cfg = lade_dcf()
    erg = dcf.bewerten(eingaben(), "IT", cfg)
    assert erg.grund is None
    assert set(cfg["branchen"]) >= {"IT", "Kommunikation", "Zyklischer Konsum", "Basiskonsum", "Gesundheit",
                                    "Finanzwerte", "Industrie", "Grundstoffe", "Energie", "Versorger", "Immobilien"}


def test_normalisierter_fcf_gilt_fuer_alle_szenarien():
    e = eingaben(fcf_ttm=40.0, fcf_jahre=[30.0, 50.0, 40.0])        # verzerrt durch Sondereffekte
    auto = dcf.bewerten(e, "Basiskonsum", CFG)
    hand = dcf.bewerten(e, "Basiskonsum", CFG, manuell={"start_fcf": 100.0})
    assert hand.manuell
    assert all(x.start_fcf == 100.0 and x.start_art == "manuell" for x in hand.szenarien.values())
    assert hand.fairer_wert > auto.fairer_wert
    # gleiche Annahmen wie test_szenarien_geordnet_und_gewichtet → Base wieder 170
    assert hand.szenarien["base"].fairer_wert == pytest.approx(170)
