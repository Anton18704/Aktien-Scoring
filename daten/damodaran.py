"""Branchendaten von Prof. Aswath Damodaran (NYU Stern), verdichtet auf die 11 Sektoren.

- KGV je Branche (aggregiert: Marktkapitalisierung ÷ Gewinn), aktuell und aus dem Archiv
- Beta je Branche (Durchschnitt der letzten 5 Jahre)
Die Dateien werden 30 Tage zwischengespeichert.
"""
from __future__ import annotations

import statistics
import time
from datetime import date

import requests
import yaml

from kern.konfig import CONFIG, PROJEKT

CACHE = PROJEKT / "cache" / "damodaran"
CACHE_GUELTIG = 30 * 24 * 3600
BASIS = "https://pages.stern.nyu.edu/~adamodar/pc"


def _laden(name: str, url: str) -> bytes | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    datei = CACHE / name
    if datei.exists() and time.time() - datei.stat().st_mtime < CACHE_GUELTIG:
        return datei.read_bytes()
    try:
        antwort = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0 AktienScoring"})
    except requests.RequestException:
        return datei.read_bytes() if datei.exists() else None
    if antwort.status_code != 200:
        return datei.read_bytes() if datei.exists() else None
    datei.write_bytes(antwort.content)
    return antwort.content


def _tabelle(inhalt: bytes, spalte_beginnt: str) -> dict[str, float]:
    """Branche → Wert aus der Spalte, deren Überschrift mit ``spalte_beginnt`` beginnt."""
    import xlrd

    buch = xlrd.open_workbook(file_contents=inhalt)
    blatt = buch.sheet_by_name("Industry Averages") if "Industry Averages" in buch.sheet_names() else buch.sheets()[-1]
    for r in range(blatt.nrows):
        if str(blatt.cell_value(r, 0)).strip() == "Industry Name":
            kopf = [str(c.value).strip() for c in blatt.row(r)]
            spalte = next((i for i, k in enumerate(kopf) if k.startswith(spalte_beginnt)), None)
            if spalte is None:
                return {}
            werte = {}
            for rr in range(r + 1, blatt.nrows):
                name = str(blatt.cell_value(rr, 0)).strip()
                try:
                    werte[name] = float(blatt.cell_value(rr, spalte))
                except (TypeError, ValueError):
                    continue
            return werte
    return {}


def zuordnung() -> dict[str, list[str]]:
    with open(CONFIG / "damodaran_branchen.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _je_sektor(werte: dict[str, float], zuo: dict[str, list[str]], min_wert: float = 0.0) -> dict[str, float]:
    klein = {k.lower(): v for k, v in werte.items()}
    ergebnis = {}
    for sektor, branchen in zuo.items():
        liste = [klein[b.lower()] for b in branchen if b.lower() in klein and klein[b.lower()] > min_wert]
        if liste:
            ergebnis[sektor] = statistics.median(liste)
    return ergebnis


def sektordaten(jahre_zurueck: int = 11) -> tuple[dict[str, dict], list[str]]:
    """{Sektor: {"kgv": aktuell, "kgv_historie": {Jahr: KGV}, "beta": Beta}} und Hinweise."""
    hinweise: list[str] = []
    zuo = zuordnung()
    ergebnis = {s: {"kgv": None, "kgv_historie": {}, "beta": None} for s in zuo}

    aktuell = _laden("pedata.xls", f"{BASIS}/datasets/pedata.xls")
    if aktuell is None:
        hinweise.append("Damodaran-KGV-Daten nicht erreichbar.")
    else:
        for s, v in _je_sektor(_tabelle(aktuell, "Aggregate Mkt Cap/ Net"), zuo).items():
            ergebnis[s]["kgv"] = v
    heute = date.today().year
    for jahr in range(heute - jahre_zurueck, heute):
        kurz = jahr % 100
        inhalt = _laden(f"pedata{kurz:02d}.xls", f"{BASIS}/archives/pedata{kurz:02d}.xls")
        if inhalt is None:
            continue
        for s, v in _je_sektor(_tabelle(inhalt, "Aggregate Mkt Cap/ Net"), zuo).items():
            ergebnis[s]["kgv_historie"][jahr] = v

    betas = _laden("betas.xls", f"{BASIS}/datasets/betas.xls")
    if betas is None:
        hinweise.append("Damodaran-Beta-Daten nicht erreichbar.")
    else:
        tab = _tabelle(betas, "Average (") or _tabelle(betas, "Beta")
        for s, v in _je_sektor(tab, zuo).items():
            ergebnis[s]["beta"] = v
    return ergebnis, hinweise
