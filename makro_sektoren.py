"""Makrodaten holen und Sektorfaktoren berechnen (Ablauf mit Internetzugriff).

Das Ergebnis wird in der Datenbank gespeichert (Einstellung "sektorfaktoren"), damit Hauptliste
und Detailansicht ohne Internet sofort darauf zugreifen können.
"""
from __future__ import annotations

from datetime import datetime

import yaml

from daten.damodaran import sektordaten
from daten.makro import fred_historie
from kern import zyklus
from kern.konfig import CONFIG
from speicher import db

MAKRO_DATEI = CONFIG / "makro.yaml"
EINSTELLUNG = "sektorfaktoren"


def lade_makro_cfg() -> dict:
    with open(MAKRO_DATEI, encoding="utf-8") as f:
        return yaml.safe_load(f)


def indikatoren_auswerten(cfg: dict) -> tuple[dict[str, zyklus.IndikatorStand], list[str]]:
    jahre, monate = int(cfg.get("historie_jahre", 10)), int(cfg.get("richtung_monate", 6))
    reihen, staende, fehler = {}, {}, []
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
    for id_, reihe in reihen.items():
        ind = cfg["indikatoren"][id_]
        einheit = "%" if ind.get("umrechnung") == "jahresrate" or "differenz" in ind else ""
        staende[id_] = zyklus.indikator_auswerten(id_, ind["name"], reihe, jahre, monate, einheit,
                                                  max_alter_monate=int(cfg.get("max_alter_monate", 6)))
    return staende, fehler


def etf_abweichungen(cfg: dict) -> dict[str, float | None]:
    from daten.kurse import von_yfinance

    ergebnis = {}
    for sektor, sc in cfg["sektoren"].items():
        try:
            ergebnis[sektor] = zyklus.etf_trendabweichung(von_yfinance(sc["etf"]).close)
        except Exception:
            ergebnis[sektor] = None
    return ergebnis


def aktualisieren(con) -> dict:
    """Holt alle Daten, berechnet die Sektorfaktoren und speichert sie. Liefert das gespeicherte Ergebnis."""
    cfg = lade_makro_cfg()
    staende, fehler = indikatoren_auswerten(cfg)
    hinweise = []
    if fehler:
        hinweise.append(f"{len(fehler)} von {len([i for i in cfg['indikatoren'].values() if 'fred' in i])} "
                        "FRED-Indikatoren nicht abrufbar: " + "; ".join(fehler[:5]) + (" …" if len(fehler) > 5 else ""))
    dam, dam_hinweise = sektordaten()
    hinweise += dam_hinweise
    etf = etf_abweichungen(cfg)
    sektoren = {}
    for sektor, sc in cfg["sektoren"].items():
        d = dam.get(sektor, {})
        st = zyklus.sektor_auswerten(sektor, sc, staende, cfg, kgv=d.get("kgv"),
                                     kgv_historie=list(d.get("kgv_historie", {}).values()),
                                     beta=d.get("beta"), etf_abweichung=etf.get(sektor))
        eintrag = st.als_dict()
        eintrag["kgv_historie"] = d.get("kgv_historie", {})
        eintrag["text"] = zyklus.faktor_text(eintrag, cfg)
        sektoren[sektor] = eintrag
    ergebnis = {"stand": datetime.now().isoformat(timespec="seconds"), "hinweise": hinweise, "sektoren": sektoren}
    db.einstellung_setzen(con, EINSTELLUNG, ergebnis)
    return ergebnis


def gespeichert(con) -> dict | None:
    return db.einstellung(con, EINSTELLUNG)


def faktor_fuer(gespeichert_: dict | None, sektor: str | None) -> dict | None:
    """Gespeicherter Stand eines Sektors oder None."""
    if not gespeichert_ or not sektor:
        return None
    return gespeichert_.get("sektoren", {}).get(sektor)
