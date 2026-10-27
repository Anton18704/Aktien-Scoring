"""Verbindet gespeicherte Analysen mit den aktuellen Schwellen und Gewichten.

Punkte, Kategorie-Scores und Gesamtscore werden bei jeder Anzeige frisch
aus den gespeicherten Rohwerten berechnet. Deshalb wirken Änderungen an
Gewichten oder Schwellenwerten sofort auf alle Titel.
"""
from __future__ import annotations

import json
from collections import defaultdict

import pandas as pd

from kern import dcf as dcf_modell
from kern import dcf_modell as eigenes
from kern.format import zahl
from kern.gesamtscore import Gesamt, einschaetzung_score, gesamtscore, kategorie_score
from kern.konfig import KATEGORIEN, lade_dcf, lade_schwellen, standardgewichte
from kern.punkte import punkte_fuer
from speicher import db


def gewichte_und_aktiv(con, schwellen: dict) -> tuple[dict[str, float], dict[str, bool]]:
    gewichte = db.einstellung(con, "gewichte", standardgewichte(schwellen))
    aktiv = db.einstellung(con, "aktiv", {k: True for k in KATEGORIEN})
    return gewichte, aktiv


def dcf_konfig(con) -> dict:
    """dcf.yaml, ergänzt um die Damodaran-Branchenwerte (falls eingestellt und schon geladen)."""
    gespeichert = db.einstellung(con, "sektorfaktoren")
    return dcf_modell.mit_damodaran(lade_dcf(), (gespeichert or {}).get("sektoren"))


def makro_stand(con) -> tuple[dict | None, bool]:
    """(gespeicherte Sektorfaktoren, Multiplikator aktiv?)."""
    import yaml
    from kern.konfig import CONFIG

    try:
        with open(CONFIG / "makro.yaml", encoding="utf-8") as f:
            aktiv = bool(yaml.safe_load(f).get("aktiv", True))
    except FileNotFoundError:
        aktiv = False
    return db.einstellung(con, "sektorfaktoren"), aktiv


def sektorfaktor(makro: dict | None, sektor: str | None) -> dict | None:
    if not makro or not sektor:
        return None
    return makro.get("sektoren", {}).get(sektor)


def mit_makro(score: float | None, faktor: dict | None, aktiv: bool) -> float | None:
    """Gesamtscore × Sektorfaktor, höchstens 100. Ohne Faktor oder ausgeschaltet: unverändert."""
    if score is None or not faktor or not aktiv:
        return score
    return min(100.0, score * float(faktor["faktor"]))


def dcf_berechnen(analyse: dict, titel: dict, manuell: dict | None, schwellen: dict, dcf_cfg: dict):
    """DCF-Bewertung einer gespeicherten Analyse mit den aktuellen Einstellungen.

    Liefert (Ergebnis, Eingaben) oder (None, None), wenn die Analyse noch keine DCF-Daten hat.
    """
    roh = analyse.get("dcf")
    if not roh:
        return None, None
    eingaben = dcf_modell.DcfEingaben.aus_dict(json.loads(roh))
    opt = schwellen["optionen"]
    erg = dcf_modell.bewerten(eingaben, db.sektor(titel), dcf_cfg, float(opt["wachstum_min"]),
                              float(opt["wachstum_max"]), manuell)
    return erg, eingaben


def dcf_zeile(analyse: dict, erg, eingaben) -> dict:
    """Die DCF-Sicherheitsmarge im Format einer gespeicherten Kennzahl (für Scores und Tabellen)."""
    zeile = {"analyse_id": analyse["id"], "schluessel": "dcf_sicherheitsmarge", "kategorie": "A",
             "rohwert": None, "fixpunkte": None, "punkte_damals": None, "quelle": "", "datenstand": "",
             "grund": None, "details": "", "hinweis": ""}
    if erg is None:
        zeile["grund"] = "Analyse stammt aus der Zeit vor dem DCF-Modell – bitte neu analysieren"
        return zeile
    zeile["grund"] = erg.grund
    if erg.grund is None:
        zeile["rohwert"] = erg.sicherheitsmarge
        zeile["details"] = dcf_modell.kurzbeschreibung(erg, eingaben)
        zeile["hinweis"] = "Annahmen teilweise manuell gesetzt" if erg.manuell else ""
    zeile["quelle"] = "; ".join(x for x in (eingaben.quelle, f"Zins: {eingaben.zins_quelle} {eingaben.zins_datum}".strip(),
                                            "Annahmen: config/dcf.yaml") if x)
    zeile["datenstand"] = eingaben.datenstand
    return zeile


def modell_vorgaben(con, titel: dict, dcf_cfg: dict) -> dict:
    """Startwerte für Beta und Exit-Multiple im eigenen DCF-Modell (Damodaran-Sektordaten, sonst Standard)."""
    sektor = db.sektor(titel)
    d = ((db.einstellung(con, "sektorfaktoren") or {}).get("sektoren") or {}).get(sektor) or {}
    v = {"sektor": sektor, "erp": float(dcf_cfg["marktrisikopraemie"]),
         "g_ewig": float(dcf_cfg["szenarien"]["base"]["langfr_wachstum"]),
         "beta": 1.0, "beta_quelle": "Standardwert 1,0 (keine Damodaran-Daten – Seite Sektoren & Zyklus aktualisieren)",
         "exit_multiple": 12.0, "multiple_quelle": "Standardwert 12 (keine Damodaran-Daten)"}
    if d.get("beta"):
        v["beta"], v["beta_quelle"] = float(d["beta"]), f"Damodaran, Sektor {sektor}"
    if d.get("ev_ebitda"):
        v["exit_multiple"] = min(max(float(d["ev_ebitda"]), 6.0), 20.0)
        v["multiple_quelle"] = f"Damodaran EV/EBITDA, Sektor {sektor} (begrenzt auf 6–20)"
    return v


def modell_basis(analyse: dict):
    roh = analyse.get("modell")
    return eigenes.ModellBasis.aus_dict(json.loads(roh)) if roh else None


def modell_zeile(analyse: dict, modell: dict) -> dict | None:
    """DCF-Sicherheitsmarge aus dem eigenen Modell; None, wenn die Analyse keine Modelldaten hat."""
    basis = modell_basis(analyse)
    if basis is None:
        return None
    a = eigenes.Annahmen.aus_dict(modell["annahmen"])
    erg = eigenes.rechnen(a, basis)
    zeile = {"analyse_id": analyse["id"], "schluessel": "dcf_sicherheitsmarge", "kategorie": "A",
             "rohwert": None, "fixpunkte": None, "punkte_damals": None, "quelle": basis.quelle,
             "datenstand": basis.datenstand, "grund": erg.grund, "details": "",
             "hinweis": f"eigenes DCF-Modell vom {modell['zeitpunkt'][:10]}"}
    if erg.grund is None:
        zeile["rohwert"] = erg.sicherheitsmarge
        zeile["details"] = (f"eigenes Modell: fairer Wert {zahl(erg.fairer_wert, 2)} {basis.waehrung} vs. Kurs "
                            f"{zahl(basis.kurs, 2)}; WACC {zahl(erg.wacc, 2)} %, ewiges Wachstum "
                            f"{zahl(a.g_ewig, 2)} %, Exit-Multiple {zahl(a.exit_multiple, 2)}× EBITDA")
    return zeile


def mit_dcf(zeilen: list[dict], analyse: dict, titel: dict, manuell, schwellen: dict, dcf_cfg: dict,
            modell: dict | None = None) -> list[dict]:
    """Ergänzt die (live berechnete) DCF-Sicherheitsmarge.

    Ist ein eigenes DCF-Modell mit „für den Score verwenden“ gespeichert, ersetzt es das automatische DCF.
    """
    zeile = None
    if modell and modell.get("im_score"):
        zeile = modell_zeile(analyse, modell)
    if zeile is None:
        erg, eingaben = dcf_berechnen(analyse, titel, manuell, schwellen, dcf_cfg)
        zeile = dcf_zeile(analyse, erg, eingaben)
    return [z for z in zeilen if z["schluessel"] != "dcf_sicherheitsmarge"] + [zeile]


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
    return scores, gesamtscore(scores, gewichte, aktiv, schwellen["optionen"]["ko_schwelle"])


def markierung(g: Gesamt, schwellen: dict | None = None) -> str:
    teile = []
    if g.ko:
        namen = (lambda k: f"{k} {schwellen['kategorien'][k]['kurz']}") if schwellen else (lambda k: k)
        teile.append("⛔ K.o.: " + ", ".join(namen(k) for k in g.ko))
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
    analysen = {r["id"]: dict(r) for r in con.execute("SELECT id, zeitpunkt, dcf, modell FROM analysen")}
    manuell, dcf_cfg, modelle = db.dcf_manuell_alle(con), dcf_konfig(con), db.dcf_modelle_alle(con)
    makro, makro_aktiv = makro_stand(con)

    zeilen = []
    for t in db.titel_alle(con):
        aid = letzte.get(t["ticker"])
        if aid is None:
            continue
        e = einsch[t["ticker"]][-1] if einsch[t["ticker"]] else None
        kz = mit_dcf(alle_zeilen[aid], analysen[aid], t, manuell.get(t["ticker"]), schwellen, dcf_cfg,
                     modelle.get(t["ticker"]))
        scores, g = bewertung(kz, e, schwellen, gewichte, aktiv)
        f = sektorfaktor(makro, db.sektor(t))
        score_makro = mit_makro(g.score, f, makro_aktiv)
        zeilen.append({
            "Name": t["name"], "Ticker": t["ticker"], "Sektor": db.sektor(t),
            "Gesamtscore": None if score_makro is None else round(score_makro, 1),
            "ohne Makro": None if g.score is None else round(g.score, 1),
            "Sektorfaktor": None if not f else round(float(f["faktor"]), 2),
            **{schwellen["kategorien"][k]["kurz"]: None if scores[k] is None else round(scores[k], 1) for k in KATEGORIEN},
            "Hinweis": markierung(g, schwellen),
            "Letzte Analyse": analysen[aid]["zeitpunkt"][:16].replace("T", " "),
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
    titel, manuell, dcf_cfg = db.titel(con, ticker), db.dcf_manuell(con, ticker), dcf_konfig(con)
    modell = db.dcf_modell(con, ticker)
    daten = []
    for a, e in zip(analysen, einsch):
        kz = mit_dcf(zeilen[a["id"]], a, titel, manuell, schwellen, dcf_cfg, modell)
        scores, g = bewertung(kz, e, schwellen, gewichte, aktiv)
        daten.append({"Zeitpunkt": pd.Timestamp(a["zeitpunkt"]), "Gesamtscore": g.score,
                      "Hinweis": markierung(g, schwellen), **{k: scores[k] for k in KATEGORIEN}})
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
    analysen = {r["id"]: dict(r) for r in con.execute("SELECT id, zeitpunkt, dcf, modell FROM analysen")}
    manuell, dcf_cfg, modelle = db.dcf_manuell_alle(con), dcf_konfig(con), db.dcf_modelle_alle(con)
    makro, makro_aktiv = makro_stand(con)
    einheiten = {s: k["einheit"] for s, k in schwellen["kennzahlen"].items()}

    daten = []
    for t in db.titel_alle(con):
        aid = letzte.get(t["ticker"])
        if aid is None:
            continue
        e = einsch[t["ticker"]][-1] if einsch[t["ticker"]] else None
        kz = mit_dcf(alle_zeilen[aid], analysen[aid], t, manuell.get(t["ticker"]), schwellen, dcf_cfg,
                     modelle.get(t["ticker"]))
        scores, g = bewertung(kz, e, schwellen, gewichte, aktiv)
        zeile = {"Name": t["name"], "Ticker": t["ticker"], "Sektor": db.sektor(t),
                 "Kategorie-Score": None if scores[kategorie] is None else round(scores[kategorie], 1)}
        if kategorie == "E":
            zeile.update({"Geschäft verstanden": e and e["f1"], "Management": e and e["f2"],
                          "10 Jahre halten": e and e["f3"], "In 10 J. größer": e and e["f4"],
                          "Begründung": e and e["begruendung"],
                          "Ich liege falsch, wenn …": e and e.get("gegenthese")})
        else:
            roh = {z["schluessel"]: z["rohwert"] for z in kz}
            for s, n in namen.items():
                einheit = f" [{einheiten[s]}]" if einheiten[s] else ""
                zeile[n + einheit] = None if roh.get(s) is None else round(roh[s], 2)
        f = sektorfaktor(makro, db.sektor(t))
        score_makro = mit_makro(g.score, f, makro_aktiv)
        zeile["Gesamtscore"] = None if score_makro is None else round(score_makro, 1)
        zeile["ohne Makro"] = None if g.score is None else round(g.score, 1)
        zeile["Hinweis"] = markierung(g, schwellen)
        daten.append(zeile)
    df = pd.DataFrame(daten)
    if not df.empty:
        df = df.sort_values("Kategorie-Score", ascending=False, na_position="last")
    return df
