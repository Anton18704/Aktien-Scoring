"""Tägliche Kursdaten.

Standard: yfinance (Yahoo Finance, kostenlos, ohne Anmeldung, inoffiziell).
Optional: Tiingo (kostenlos mit Anmeldung) – wird genutzt, wenn in
config/settings.toml ein ``tiingo_api_key`` eingetragen ist. Fällt die
bevorzugte Quelle aus, wird automatisch die andere versucht.

Gespeichert wird der Schlusskurs, um Aktiensplits bereinigt, aber ohne
Dividendenbereinigung (also der Kurs, den man im Chart sieht).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd
import requests


class KursFehler(Exception):
    pass


@dataclass
class Kursdaten:
    close: pd.Series                                   # Index: Datum (ohne Zeitzone)
    splits: list[tuple[date, float]] = field(default_factory=list)
    waehrung: str | None = None
    quelle: str = ""


def _yahoo_symbol(ticker: str) -> str:
    return ticker.strip().upper().replace(".", "-")


def von_yfinance(ticker: str, jahre: int = 12) -> Kursdaten:
    import yfinance as yf

    sym = _yahoo_symbol(ticker)
    t = yf.Ticker(sym)
    start = date.today() - timedelta(days=round(365.25 * jahre))
    df = t.history(start=start.isoformat(), auto_adjust=False, actions=True)
    if df is None or df.empty:
        raise KursFehler(f"yfinance liefert keine Kurse für {sym}.")
    close = df["Close"].copy()
    close.index = pd.DatetimeIndex(close.index).tz_localize(None).normalize()
    alle_splits = t.splits
    splits = []
    if alle_splits is not None and not alle_splits.empty:
        splits = [(pd.Timestamp(d).date(), float(v)) for d, v in alle_splits.items() if v and v > 0]
    waehrung = (getattr(t, "history_metadata", None) or {}).get("currency")
    return Kursdaten(close.dropna(), splits, waehrung, f"yfinance/Yahoo Finance, Stand {close.index[-1].date()}")


def von_tiingo(ticker: str, api_key: str, jahre: int = 12) -> Kursdaten:
    sym = _yahoo_symbol(ticker).lower()
    start = date.today() - timedelta(days=round(365.25 * jahre))
    url = f"https://api.tiingo.com/tiingo/daily/{sym}/prices"
    antwort = requests.get(url, params={"startDate": start.isoformat(), "token": api_key}, timeout=30)
    if antwort.status_code != 200:
        raise KursFehler(f"Tiingo antwortet mit Status {antwort.status_code}.")
    daten = antwort.json()
    if not daten:
        raise KursFehler(f"Tiingo liefert keine Kurse für {sym}.")
    df = pd.DataFrame(daten)
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    df = df.set_index("date").sort_index()
    # Tiingo liefert unbereinigte Kurse + Splitfaktor. Auf heutige Basis umrechnen:
    faktor_danach = df["splitFactor"][::-1].cumprod()[::-1].shift(-1).fillna(1.0)
    close = df["close"] / faktor_danach
    splits = [(d.date(), float(v)) for d, v in df["splitFactor"].items() if v != 1.0]
    return Kursdaten(close, splits, "USD", f"Tiingo, Stand {close.index[-1].date()}")


def lade_kurse(ticker: str, tiingo_key: str = "") -> tuple[Kursdaten, list[str]]:
    """Lädt Kurse aus der bevorzugten Quelle, bei Fehler aus der anderen."""
    hinweise = []
    reihenfolge = ["tiingo", "yfinance"] if tiingo_key else ["yfinance"]
    fehler = []
    for quelle in reihenfolge:
        try:
            if quelle == "tiingo":
                return von_tiingo(ticker, tiingo_key), hinweise
            kd = von_yfinance(ticker)
            if fehler:
                hinweise.append("Tiingo nicht verfügbar, Kurse von yfinance.")
            return kd, hinweise
        except Exception as ex:
            fehler.append(f"{quelle}: {ex}")
    raise KursFehler("Keine Kursdaten: " + " | ".join(fehler))
