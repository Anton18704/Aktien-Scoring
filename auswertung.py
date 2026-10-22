"""Verbindet gespeicherte Analysen mit den aktuellen Schwellen und Gewichten.

Punkte, Kategorie-Scores und Gesamtscore werden bei jeder Anzeige frisch
aus den gespeicherten Rohwerten berechnet. Deshalb wirken Änderungen an
Gewichten oder Schwellenwerten sofort auf alle Titel.
"""
from __future__ import annotations

from collections import defaultdict

import pandas as pd

from kern.gesamtscore import Gesamt, einschaetzung_score, gesamtscore, kategorie_score
from kern.konfig import KATEGORIEN, lade_schwellen, standardgewichte
from kern.punkte import punkte_fuer
from speicher import db


def gewichte_und_aktiv(con, schwellen: dict) -> tuple[dict[str, float], dict[str, bool]]:
    gewichte = db.einstellung(con, "gewichte", standardgewichte(schwellen))
    aktiv = db.einstellung(con, "aktiv", {k: True for k in KATEGORIEN})
    return gewichte, aktiv


def punkte_zeile(zeile: dict, schwellen: dict) -> float | None:
    if zeile["schluessel"] not in schwellen["kennzahlen"]:
        return None
    if zeile["grund"] and zeile["fixpunkte"] is None:
        return None
    return punkte_fuer(zeile["schluessel"], zeile["rohwert"], zeile["fixpunkte"], schwellen)


def kategorie_scores(zeilen: list[dict], schwellen: dict) -> dict[str, float | None]:
    pro_kat = defaultdict(list)
    for z in zeilen:
        pro_kat[z["kategorie"]].append(punkte_zeile(z, schwellen))
    return {k: kategorie_score(pro_kat.get(k, [])) for k in KATEGORIEN if k != "E"}


def einschaetzung_fuer_analysen(analysen: list[dict], einschaetzungen: list[dict]) -> list[dict | None]:
    """Gültige Einschätzung je Analyse: die letzte, die vor der nächsten Analyse abgegeben wurde."""
    ergebnis = []
    for i, a in enumerate(analysen):
        grenze = analysen[i + 1]["zeitpunkt"] if i + 1 < len(analysen) else None
        passend = [e for e in einschaetzungen if grenze is None or e["zeitpunkt"] < grenze]
        ergebnis.append(passend[-1] if passend else None)
    return ergebnis


def e_score(e: dict | None) -> float | None:
    return einschaetzung_score(e["f1"], e["f2"], e["f3"], e["f4"]) if e else None


def bewertung(zeilen, einschaetzung, schwellen, gewichte, aktiv) -> tuple[dict, Gesamt]:
    scores = kategorie_scores(zeilen, schwellen)
    scores["E"] = e_score(einschaetzung)
    return scores, gesamtscore(scores, gewichte, aktiv)


def markierung(g: Gesamt) -> str:
    teile = []
    if g.einschaetzung_offen:
        teile.append("Einschätzung offen")
    if g.unvollstaendig:
        teile.append("unvollständig (fehlt: " + ", ".join(k for k in g.fehlende if k != "E") + ")")
    return " · ".join(teile)


def uebersicht(con) -> pd.DataFrame:
    """Eine Zeile pro Titel mit den Scores der letzten Analyse."""
    schwellen = lade_schwellen()
    gewichte, aktiv = gewichte_und_aktiv(con, schwellen)
    letzte = db.letzte_analyse_ids(con)
    alle_zeilen = defaultdict(list)
    for z in db.kennzahlen_fuer(con, list(letzte.values())):
        alle_zeilen[z["analyse_id"]].append(z)
    einsch = defaultdict(list)
    for e in db.einschaetzungen_alle(con):
        einsch[e["ticker"]].append(e)
    zeitpunkte = {a: z for a, z in con.execute("SELECT id, zeitpunkt FROM analysen")}

    zeilen = []
    for t in db.titel_alle(con):
        aid = letzte.get(t["ticker"])
        if aid is None:
            continue
        e = einsch[t["ticker"]][-1] if einsch[t["ticker"]] else None
        scores, g = bewertung(alle_zeilen[aid], e, schwellen, gewichte, aktiv)
        zeilen.append({
            "Name": t["name"], "Ticker": t["ticker"], "Sektor": db.sektor(t),
            "Gesamtscore": None if g.score is None else round(g.score, 1),
            **{schwellen["kategorien"][k]["kurz"]: None if scores[k] is None else round(scores[k], 1) for k in KATEGORIEN},
            "Hinweis": markierung(g),
            "Letzte Analyse": zeitpunkte[aid][:16].replace("T", " "),
        })
    return pd.DataFrame(zeilen)


def kennzahlen_tabelle(zeilen: list[dict], schwellen: dict, kategorie: str) -> pd.DataFrame:
    daten = []
    for z in zeilen:
        if z["kategorie"] != kategorie or z["schluessel"] not in schwellen["kennzahlen"]:
            continue
        k = schwellen["kennzahlen"][z["schluessel"]]
        p = punkte_zeile(z, schwellen)
        daten.append({
            "Kennzahl": k["name"],
            "Rohwert": None if z["rohwert"] is None else round(z["rohwert"], 2),
            "Einheit": k["einheit"],
            "Punkte": None if p is None else round(p, 1),
            "Schwellen 10/5/0": f"{k['zehn']:g} / {k['fuenf']:g} / {k['null']:g}",
            "Rechenweg": z["details"] or "",
            "Hinweis / Grund": z["grund"] or z["hinweis"] or "",
            "Datenstand": z["datenstand"] or "",
            "Quelle": z["quelle"] or "",
        })
    return pd.DataFrame(daten)


def verlauf(con, ticker: str) -> pd.DataFrame:
    schwellen = lade_schwellen()
    gewichte, aktiv = gewichte_und_aktiv(con, schwellen)
    analysen = db.analysen_fuer(con, ticker)
    einsch = einschaetzung_fuer_analysen(analysen, db.einschaetzungen_fuer(con, ticker))
    zeilen = defaultdict(list)
    for z in db.kennzahlen_fuer(con, [a["id"] for a in analysen]):
        zeilen[z["analyse_id"]].append(z)
    daten = []
    for a, e in zip(analysen, einsch):
        scores, g = bewertung(zeilen[a["id"]], e, schwellen, gewichte, aktiv)
        daten.append({"Zeitpunkt": pd.Timestamp(a["zeitpunkt"]), "Gesamtscore": g.score,
                      "Hinweis": markierung(g), **{k: scores[k] for k in KATEGORIEN}})
    return pd.DataFrame(daten)


def kategorie_ansicht(con, kategorie: str) -> pd.DataFrame:
    """Alle Titel mit Score und Rohwerten einer Kategorie (A–E)."""
    schwellen = lade_schwellen()
    gewichte, aktiv = gewichte_und_aktiv(con, schwellen)
    letzte = db.letzte_analyse_ids(con)
    alle_zeilen = defaultdict(list)
    for z in db.kennzahlen_fuer(con, list(letzte.values())):
        alle_zeilen[z["analyse_id"]].append(z)
    einsch = defaultdict(list)
    for e in db.einschaetzungen_alle(con):
        einsch[e["ticker"]].append(e)
    namen = {s: k["name"] for s, k in schwellen["kennzahlen"].items() if k["kategorie"] == kategorie}
    einheiten = {s: k["einheit"] for s, k in schwellen["kennzahlen"].items()}

    daten = []
    for t in db.titel_alle(con):
        aid = letzte.get(t["ticker"])
        if aid is None:
            continue
        e = einsch[t["ticker"]][-1] if einsch[t["ticker"]] else None
        scores, g = bewertung(alle_zeilen[aid], e, schwellen, gewichte, aktiv)
        zeile = {"Name": t["name"], "Ticker": t["ticker"], "Sektor": db.sektor(t),
                 "Kategorie-Score": None if scores[kategorie] is None else round(scores[kategorie], 1)}
        if kategorie == "E":
            zeile.update({"Geschäft verstanden": e and e["f1"], "Management": e and e["f2"],
                          "10 Jahre halten": e and e["f3"], "In 10 J. größer": e and e["f4"],
                          "Begründung": e and e["begruendung"]})
        else:
            roh = {z["schluessel"]: z["rohwert"] for z in alle_zeilen[aid]}
            for s, n in namen.items():
                einheit = f" [{einheiten[s]}]" if einheiten[s] else ""
                zeile[n + einheit] = None if roh.get(s) is None else round(roh[s], 2)
        zeile["Gesamtscore"] = None if g.score is None else round(g.score, 1)
        zeile["Hinweis"] = markierung(g)
        daten.append(zeile)
    df = pd.DataFrame(daten)
    if not df.empty:
        df = df.sort_values("Kategorie-Score", ascending=False, na_position="last")
    return df
