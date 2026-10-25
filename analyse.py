"""Führt eine Analyse durch: Daten holen, Kennzahlen berechnen, speichern."""
from __future__ import annotations

from dataclasses import dataclass

from daten.kurse import KursFehler, lade_kurse
from daten.sec import SecClient, SecFehler
from daten.xbrl import finanzdaten_aus
from kern.kennzahlen import alle_berechnen
from kern.konfig import lade_schwellen, lade_settings, sektor_fuer_sic
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


def kennzahlen_berechnen(ticker: str, frisch: bool = False) -> Rohdaten:
    """Holt alle Daten und berechnet die Kennzahlen, ohne etwas zu speichern."""
    ticker = ticker.strip().upper().replace(".", "-")
    if not ticker:
        raise AnalyseFehler("Leerer Ticker.")
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
    return Rohdaten(ticker, cik, name, str(sub.get("sic") or ""), sub.get("sicDescription", ""),
                    fd, alle_berechnen(fd), hinweise)


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
    )
    return AnalyseErgebnis(r.ticker, r.name, analyse_id, r.hinweise)


def tickers_aus_csv(datei) -> list[str]:
    """Liest eine CSV-Datei mit einer Spalte 'Ticker' (Komma oder Semikolon getrennt)."""
    import pandas as pd

    df = pd.read_csv(datei, sep=None, engine="python", dtype=str)
    spalte = next((c for c in df.columns if c.strip().lower() == "ticker"), None)
    if spalte is None:
        raise AnalyseFehler("Die CSV-Datei braucht eine Spalte mit der Überschrift 'Ticker'.")
    tickers = [t.strip().upper() for t in df[spalte].dropna() if t.strip()]
    return list(dict.fromkeys(tickers))  # doppelte entfernen, Reihenfolge behalten
