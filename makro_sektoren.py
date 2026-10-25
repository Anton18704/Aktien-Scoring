"""Makrodaten holen und Sektorfaktoren berechnen (Ablauf mit Internetzugriff).

Das Ergebnis wird in der Datenbank gespeichert (Einstellung "sektorfaktoren"), damit Hauptliste
und Detailansicht ohne Internet sofort darauf zugreifen können. Jede Aktualisierung kommt
außerdem in den Verlauf (Tabelle sektor_verlauf).
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import yaml

from daten.damodaran import sektordaten
from daten.makro import fred_historie
from kern import zyklus
from kern.konfig import CONFIG
from speicher import db

MAKRO_DATEI = CONFIG / "makro.yaml"
EINSTELLUNG = "sektorfaktoren"
VEROEFFENTLICHUNG_MONATE = 1   # Verzug bei der Rückrechnung: Monatsdaten erscheinen erst im Folgemonat


def lade_makro_cfg() -> dict:
    with open(MAKRO_DATEI, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------- Daten laden

def lade_reihen(cfg: dict) -> tuple[dict[str, pd.Series], list[str]]:
    """Alle Indikatoren als umgerechnete Monatsreihen."""
    reihen, fehler = {}, []
    for id_, ind in cfg["indikatoren"].items():
        if "fred" not in ind:
            continue
        try:
            reihen[id_] = zyklus.umrechnen(zyklus.monatlich(fred_historie(ind["fred"])), ind.get("umrechnung", "niveau"))
        except Exception as ex:
            fehler.append(f"{ind['name']} ({ind['fred']}): {type(ex).__name__}")
    for id_, ind in cfg["indikatoren"].items():
        if "differenz" in ind:
            a, b = ind["differenz"]
            if a in reihen and b in reihen:
                reihen[id_] = (reihen[a] - reihen[b]).dropna()
    return reihen, fehler


def lade_etf_kurse(cfg: dict) -> dict[str, pd.Series | None]:
    from daten.kurse import von_yfinance

    kurse = {}
    for sektor, sc in cfg["sektoren"].items():
        try:
            kurse[sektor] = von_yfinance(sc["etf"]).close
        except Exception:
            kurse[sektor] = None
    return kurse


# ---------------------------------------------------------------- Rechnen

def _kgv_zum(d: dict, stichtag: pd.Timestamp | None) -> tuple[float | None, list[float]]:
    """(KGV, Historie) – live: aktuelles KGV vs. Archiv; Rückrechnung: KGV des Jahres vs. frühere Jahre."""
    hist = {int(j): v for j, v in (d.get("kgv_historie") or {}).items()}
    if stichtag is None:
        return d.get("kgv"), list(hist.values())
    frueher = sorted(j for j in hist if j <= stichtag.year)
    if not frueher:
        return None, []
    jahr = frueher[-1]
    return hist[jahr], [hist[j] for j in frueher if j < jahr]


def sektoren_berechnen(cfg: dict, staende: dict, dam: dict, etf_kurse: dict,
                       stichtag: pd.Timestamp | None = None) -> dict[str, dict]:
    sektoren = {}
    for sektor, sc in cfg["sektoren"].items():
        d = dam.get(sektor, {})
        kgv, kgv_hist = _kgv_zum(d, stichtag)
        kurse = etf_kurse.get(sektor)
        if kurse is not None and stichtag is not None:
            kurse = kurse.loc[:stichtag]
        st = zyklus.sektor_auswerten(sektor, sc, staende, cfg, kgv=kgv, kgv_historie=kgv_hist, beta=d.get("beta"),
                                     etf_abweichung=zyklus.etf_trendabweichung(kurse) if kurse is not None else None)
        eintrag = st.als_dict()
        eintrag["kgv_historie"] = d.get("kgv_historie", {})
        eintrag["text"] = zyklus.faktor_text(eintrag, cfg)
        sektoren[sektor] = eintrag
    return sektoren


def _verlaufszeilen(sektoren: dict, monat: str, quelle: str) -> list[dict]:
    return [{"monat": monat, "sektor": n, "faktor": s["faktor"], "grundfaktor": s["grundfaktor"], "bonus": s["bonus"],
             "phase": s["phase"], "phase_roh": s.get("phase_roh", s["phase"]), "niveau": s["niveau"],
             "richtung": s["richtung"], "quelle": quelle} for n, s in sektoren.items()]


def _bestaetigen_live(con, sektoren: dict, cfg: dict, monat: str) -> dict:
    """Bestätigungsregel für die Live-Werte anhand der gespeicherten Vormonate."""
    monate = int(cfg.get("bestaetigung_monate", 1))
    if monate <= 1:
        return sektoren
    frueher: dict[str, list[dict]] = {}
    for r in db.sektor_verlauf(con):
        if r["monat"] < monat:
            frueher.setdefault(r["sektor"], []).append(r)
    ergebnis = {}
    for n, e in sektoren.items():
        hist = frueher.get(n, [])
        if not hist:
            ergebnis[n] = e
            continue
        bisher = hist[-1]["phase"]                                   # zuletzt gültige Phase
        roh = [r.get("phase_roh") or r["phase"] for r in hist[-(monate - 1):]] + [e["phase"]]
        bestaetigt = e["phase"] != bisher and len(roh) == monate and all(p == e["phase"] for p in roh)
        ergebnis[n] = zyklus.phase_setzen(e, e["phase"] if bestaetigt or e["phase"] == bisher else bisher, cfg)
    return ergebnis


def aktualisieren(con) -> dict:
    """Holt alle Daten, berechnet die Sektorfaktoren und speichert sie. Liefert das gespeicherte Ergebnis.

    Wurden die Regeln (makro.yaml) seit der letzten Rückrechnung geändert, wird der Verlauf zuerst neu
    nachgerechnet – sonst würde die Bestätigungsregel auf Phasen nach alten Regeln aufbauen.
    """
    cfg = lade_makro_cfg()
    if db.einstellung(con, "rekonstruktion_regeln") not in (None, regeln_kennung()):
        rekonstruieren(con)
    reihen, fehler = lade_reihen(cfg)
    hinweise = []
    if fehler:
        hinweise.append(f"{len(fehler)} von {len([i for i in cfg['indikatoren'].values() if 'fred' in i])} "
                        "FRED-Indikatoren nicht abrufbar: " + "; ".join(fehler[:5]) + (" …" if len(fehler) > 5 else ""))
    dam, dam_hinweise = sektordaten()
    hinweise += dam_hinweise
    staende = zyklus.staende_zum_stichtag(reihen, cfg)
    unbrauchbar = [f"{s.name}: {s.grund}" for s in staende.values() if s.grund]
    if unbrauchbar:
        hinweise.append(f"{len(unbrauchbar)} Indikator(en) werden nicht verwendet – " + "; ".join(unbrauchbar))
    sektoren = sektoren_berechnen(cfg, staende, dam, lade_etf_kurse(cfg))
    jetzt = datetime.now()
    sektoren = _bestaetigen_live(con, sektoren, cfg, jetzt.strftime("%Y-%m"))
    ergebnis = {"stand": jetzt.isoformat(timespec="seconds"), "hinweise": hinweise, "sektoren": sektoren}
    db.einstellung_setzen(con, EINSTELLUNG, ergebnis)
    db.sektor_verlauf_speichern(con, _verlaufszeilen(sektoren, jetzt.strftime("%Y-%m"), "live"))
    return ergebnis


def rekonstruieren(con, monate: int = 36) -> int:
    """Verlauf der letzten ``monate`` Monate aus historischen Daten nachrechnen.

    Für jedes Monatsende werden nur Daten verwendet, die damals schon veröffentlicht waren
    (ein Monat Verzug). Frühere Rekonstruktionen werden ersetzt, Live-Einträge bleiben.
    Liefert die Anzahl der berechneten Monate.
    """
    cfg = lade_makro_cfg()
    reihen, _ = lade_reihen(cfg)
    dam, _ = sektordaten()
    etf = lade_etf_kurse(cfg)
    heute = pd.Timestamp.today().normalize()
    stichtage = pd.date_range(end=heute - pd.offsets.MonthEnd(1), periods=monate, freq="ME")
    je_monat = []
    for stichtag in stichtage:
        staende = zyklus.staende_zum_stichtag(reihen, cfg, stichtag, VEROEFFENTLICHUNG_MONATE)
        je_monat.append((stichtag, sektoren_berechnen(cfg, staende, dam, etf, stichtag)))
    monate_b = int(cfg.get("bestaetigung_monate", 1))
    for sektor in cfg["sektoren"]:
        gueltig = zyklus.bestaetigte_phasen([m[sektor]["phase"] for _, m in je_monat], monate_b)
        for (_, m), phase in zip(je_monat, gueltig):
            m[sektor] = zyklus.phase_setzen(m[sektor], phase, cfg)
    zeilen = []
    for stichtag, sektoren in je_monat:
        zeilen += _verlaufszeilen(sektoren, stichtag.strftime("%Y-%m"), "rekonstruiert")
    db.sektor_verlauf_ersetzen_rekonstruiert(con, zeilen)
    db.einstellung_setzen(con, "rekonstruktion_regeln", regeln_kennung())
    return len(stichtage)


def gespeichert(con) -> dict | None:
    return db.einstellung(con, EINSTELLUNG)


# ---------------------------------------------------------------- Prüfstand

PRUEFSTAND = "pruefstand"


def regeln_kennung() -> str:
    """Prüfsumme von makro.yaml – zeigt an, ob sich die Regeln seit dem letzten Test geändert haben."""
    import hashlib
    return hashlib.md5(MAKRO_DATEI.read_bytes()).hexdigest()[:10]


def pruefstand(con, start: str = "2008-01-31", horizont_monate: int = 12, fortschritt=None) -> dict:
    """Rechnet die Sektorfaktoren für jeden Monat seit ``start`` genau so nach, wie die App sie live
    berechnet (nur damals veröffentlichte Daten, Glättung, Bestätigungsregel, Bewertungsbonus), und
    vergleicht sie mit der Rendite der Sektor-ETFs in den folgenden Monaten relativ zum S&P 500."""
    from daten.kurse import von_yfinance
    from kern import pruefstand as ps

    cfg = lade_makro_cfg()
    reihen, _ = lade_reihen(cfg)
    dam, _ = sektordaten()
    etf_taeglich = {}
    for sektor, sc in cfg["sektoren"].items():
        try:
            etf_taeglich[sektor] = von_yfinance(sc["etf"], jahre=30).close
        except Exception:
            etf_taeglich[sektor] = None
    spy = von_yfinance("SPY", jahre=30).close.resample("ME").last()
    etf_monat = {s: (k.resample("ME").last() if k is not None else None) for s, k in etf_taeglich.items()}

    letzter = pd.Timestamp.today().normalize() - pd.offsets.MonthEnd(horizont_monate + 1)
    monate = pd.date_range(start, letzter, freq="ME")
    je_monat = []
    for i, m in enumerate(monate):
        staende = zyklus.staende_zum_stichtag(reihen, cfg, m, VEROEFFENTLICHUNG_MONATE)
        je_monat.append((m, sektoren_berechnen(cfg, staende, dam, etf_taeglich, m)))
        if fortschritt:
            fortschritt((i + 1) / len(monate))
    monate_b = int(cfg.get("bestaetigung_monate", 1))
    zeilen = []
    for sektor in cfg["sektoren"]:
        gueltig = zyklus.bestaetigte_phasen([m[sektor]["phase"] for _, m in je_monat], monate_b)
        kurse = etf_monat.get(sektor)
        for (m, sektoren), phase in zip(je_monat, gueltig):
            e = zyklus.phase_setzen(sektoren[sektor], phase, cfg)
            ende = m + pd.offsets.MonthEnd(horizont_monate)
            if kurse is None or any(pd.isna(x.get(t)) for x in (kurse, spy) for t in (m, ende)):
                continue
            rel = ((kurse[ende] / kurse[m]) / (spy[ende] / spy[m]) - 1) * 100
            zeilen.append({"monat": m, "sektor": sektor, "phase": e["phase"], "faktor": e["faktor"], "rel": rel})
    ergebnis = ps.auswerten(pd.DataFrame(zeilen), cfg["phasen"])
    ergebnis.update({"stand": datetime.now().isoformat(timespec="seconds"), "regeln": regeln_kennung(),
                     "horizont_monate": horizont_monate})
    db.einstellung_setzen(con, PRUEFSTAND, ergebnis)
    return ergebnis


def letzter_pruefstand(con) -> dict | None:
    return db.einstellung(con, PRUEFSTAND)
