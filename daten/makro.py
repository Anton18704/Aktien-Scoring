"""Makrodaten von FRED (Federal Reserve Bank of St. Louis), kostenlos und ohne Anmeldung."""
from __future__ import annotations

import csv
import io
import time
from datetime import date

import requests

from kern.konfig import PROJEKT

CACHE = PROJEKT / "cache"
CACHE_GUELTIG = 12 * 3600


def _fred_text(reihe: str) -> str:
    CACHE.mkdir(exist_ok=True)
    datei = CACHE / f"fred_{reihe}.csv"
    if datei.exists() and time.time() - datei.stat().st_mtime < CACHE_GUELTIG:
        return datei.read_text(encoding="utf-8")
    try:
        antwort = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": reihe}, timeout=20)
        antwort.raise_for_status()
    except requests.RequestException:
        if datei.exists():          # lieber ältere Daten als gar keine
            return datei.read_text(encoding="utf-8")
        raise
    datei.write_text(antwort.text, encoding="utf-8")
    return antwort.text


def fred_historie(reihe: str):
    """Ganze FRED-Zeitreihe als pandas.Series (Index = Datum)."""
    import pandas as pd

    daten = {}
    for zeile in list(csv.reader(io.StringIO(_fred_text(reihe))))[1:]:
        if len(zeile) >= 2 and zeile[1] not in ("", "."):
            try:
                daten[pd.Timestamp(zeile[0])] = float(zeile[1])
            except ValueError:
                continue
    if not daten:
        raise ValueError(f"FRED-Reihe {reihe} enthält keine Werte.")
    return pd.Series(daten).sort_index()


def fred_reihe(reihe: str) -> tuple[float, date]:
    """Letzter verfügbarer Wert einer FRED-Zeitreihe, z. B. DGS10 (10-jährige US-Staatsanleihe)."""
    s = fred_historie(reihe)
    return float(s.iloc[-1]), s.index[-1].date()


def risikofreier_zins(cfg: dict) -> tuple[float, str, str, str | None]:
    """(Zins in %, Datum, Quelle, Hinweis). Fällt FRED aus, wird der Ersatzwert aus dcf.yaml genommen."""
    einst = cfg.get("risikofreier_zins", {})
    ersatz = float(einst.get("ersatzwert", 4.25))
    if einst.get("quelle", "fred") != "fred":
        return ersatz, "", "fester Wert aus config/dcf.yaml", None
    reihe = einst.get("fred_reihe", "DGS10")
    try:
        wert, datum = fred_reihe(reihe)
        return wert, datum.isoformat(), f"FRED {reihe} (Rendite 10-jährige US-Staatsanleihe)", None
    except Exception as ex:
        return ersatz, "", "Ersatzwert aus config/dcf.yaml", (
            f"FRED nicht erreichbar ({type(ex).__name__}) – für das DCF-Modell wird der Ersatzzins "
            f"von {ersatz:.2f} % verwendet.")
