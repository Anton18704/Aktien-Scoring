"""Führt eine Analyse durch: Daten holen, Kennzahlen berechnen, speichern."""
from __future__ import annotations

from dataclasses import dataclass

from daten.kurse import KursFehler, lade_kurse
from daten.sec import SecClient, SecFehler
from daten.xbrl import finanzdaten_aus
from daten.makro import risikofreier_zins
from kern.kennzahlen import alle_berechnen, dcf_eingaben
from kern.konfig import KonfigFehler, lade_dcf, lade_schwellen, lade_settings, sektor_fuer_sic
from kern.punkte import punkte_fuer
from speicher import db


class AnalyseFehler(Exception):
    pass


@dataclass
class AnalyseErgebnis:
    ticker: str
    name: str
    analyse_id: int
    hinweise: list[str]


def _client() -> tuple[SecClient, dict]:
    settings = lade_settings()
    if not settings or not settings.get("sec", {}).get("email"):
        raise AnalyseFehler("Bitte zuerst auf der Seite 'Einstellungen' die Kontakt-E-Mail für die SEC eintragen.")
    return SecClient(settings["sec"]["email"], settings["sec"].get("app_name", "AktienScoring")), settings


@dataclass
class Rohdaten:
    ticker: str
    cik: int
    name: str
    sic: str
    sic_beschreibung: str
    fd: object
    ergebnisse: list
    hinweise: list[str]
    dcf: object = None          # kern.dcf.DcfEingaben


def kennzahlen_berechnen(ticker: str, frisch: bool = False) -> Rohdaten:
    """Holt alle Daten und berechnet die Kennzahlen, ohne etwas zu speichern."""
    ticker = ticker.strip().upper().replace(".", "-")
    if not ticker:
        raise AnalyseFehler("Leerer Ticker.")
    try:
        lade_schwellen()
        lade_dcf()
    except KonfigFehler as ex:
        raise AnalyseFehler(str(ex)) from ex
    client, settings = _client()
    try:
        if frisch:
            client.json("https://www.sec.gov/files/company_tickers.json", "company_tickers.json", frisch=True)
        cik = client.cik_fuer(ticker)
        sub = client.json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", f"submissions_{cik}.json", frisch)
        facts = client.json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json",
                            f"companyfacts_{cik}.json", frisch)
    except SecFehler as ex:
        raise AnalyseFehler(str(ex)) from ex

    hinweise: list[str] = []
    try:
        kurse, kurs_hinweise = lade_kurse(ticker, settings.get("kurse", {}).get("tiingo_api_key", ""))
        hinweise += kurs_hinweise
    except KursFehler as ex:
        kurse = None
        hinweise.append(f"Keine Kursdaten ({ex}). Kennzahlen mit Marktkapitalisierung entfallen.")

    fd, xbrl_hinweise = finanzdaten_aus(facts, kurse)
    hinweise += xbrl_hinweise
    optionen = lade_schwellen()["optionen"]
    fd.fcf_abzug_aktienverguetung = bool(optionen["fcf_abzug_aktienverguetung"])
    fd.wachstum_min, fd.wachstum_max = float(optionen["wachstum_min"]), float(optionen["wachstum_max"])
    if not fd.jahre and not fd.bilanz:
        raise AnalyseFehler(f"Für {ticker} gibt es bei der SEC keine verwertbaren XBRL-Abschlussdaten "
                            "(z. B. weil das Unternehmen nicht bei der SEC berichtet).")
    name = sub.get("name") or facts.get("entityName") or ticker
    dcf = dcf_eingaben(fd)
    dcf.zins, dcf.zins_datum, dcf.zins_quelle, zins_hinweis = risikofreier_zins(lade_dcf())
    if zins_hinweis:
        hinweise.append(zins_hinweis)
    return Rohdaten(ticker, cik, name, str(sub.get("sic") or ""), sub.get("sicDescription", ""),
                    fd, alle_berechnen(fd), hinweise, dcf)


def analysieren(con, ticker: str, frisch: bool = False) -> AnalyseErgebnis:
    """Berechnet die Kennzahlen und speichert sie als neue Analyse (nichts wird überschrieben)."""
    r = kennzahlen_berechnen(ticker, frisch)
    schwellen = lade_schwellen()
    db.titel_speichern(con, r.ticker, r.cik, r.name, r.sic, r.sic_beschreibung, sektor_fuer_sic(r.sic), r.fd.waehrung)
    analyse_id = db.analyse_speichern(
        con, r.ticker, r.fd.waehrung, r.ergebnisse,
        kategorie_von=lambda s: schwellen["kennzahlen"][s]["kategorie"],
        punkte_von=lambda e: punkte_fuer(e.schluessel, e.rohwert, e.fixpunkte, schwellen),
        hinweise=r.hinweise,
        dcf=r.dcf.als_dict() if r.dcf else None,
    )
    return AnalyseErgebnis(r.ticker, r.name, analyse_id, r.hinweise)


def firmen_liste() -> dict[str, dict]:
    """Alle bei der SEC bekannten Ticker mit Firmennamen (1 Tag zwischengespeichert)."""
    client, _ = _client()
    try:
        return client.ticker_liste()
    except SecFehler as ex:
        raise AnalyseFehler(str(ex)) from ex


def _normal(text: str) -> str:
    import re
    text = text.lower().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text).split())


def suche_firmen(begriff: str, liste: dict[str, dict], max_treffer: int = 15) -> list[tuple[str, str]]:
    """Firmen per Name oder Ticker finden. Liefert [(Ticker, Name)], beste Treffer zuerst.

    Reihenfolge: exakter Ticker, Ticker beginnt mit …, Name beginnt mit …, alle Suchwörter im Namen,
    Suchbegriff irgendwo im Namen. Bei Gleichstand zuerst die größeren Firmen (Reihenfolge der SEC-Liste).
    """
    b = _normal(begriff)
    if not b:
        return []
    b_ticker = begriff.strip().upper().replace(".", "-")
    woerter = b.split()
    b_kompakt = b.replace(" ", "")
    treffer = []
    for rang, (ticker, info) in enumerate(liste.items()):
        name = _normal(info["name"])
        name_woerter = name.split()
        if ticker == b_ticker:
            stufe = 0
        elif ticker.startswith(b_ticker) and len(b_ticker) >= 2:
            stufe = 1
        elif name.startswith(b):
            stufe = 2
        elif all(any(nw.startswith(w) for nw in name_woerter) for w in woerter):
            stufe = 3
        elif name.replace(" ", "").startswith(b_kompakt):        # "mc donalds" findet "MCDONALDS CORP"
            stufe = 3
        elif len(b_kompakt) >= 4 and b_kompakt in name.replace(" ", ""):
            stufe = 4                                             # Teilwort erst ab 4 Buchstaben (weniger Rauschen)
        else:
            continue
        treffer.append((stufe, rang, ticker, info["name"]))
    treffer.sort()
    return [(t, n) for _, _, t, n in treffer[:max_treffer]]


def tickers_aus_csv(datei) -> list[str]:
    """Liest eine CSV-Datei mit einer Spalte 'Ticker' (Komma oder Semikolon getrennt)."""
    import pandas as pd

    df = pd.read_csv(datei, sep=None, engine="python", dtype=str)
    spalte = next((c for c in df.columns if c.strip().lower() == "ticker"), None)
    if spalte is None:
        raise AnalyseFehler("Die CSV-Datei braucht eine Spalte mit der Überschrift 'Ticker'.")
    tickers = [t.strip().upper() for t in df[spalte].dropna() if t.strip()]
    return list(dict.fromkeys(tickers))  # doppelte entfernen, Reihenfolge behalten
