"""Abruf von SEC-EDGAR-Daten unter Einhaltung der SEC-Regeln.

- Jeder Abruf trägt einen User-Agent mit Kontakt-E-Mail (aus config/settings.toml).
- Höchstens 10 Anfragen pro Sekunde (hier sicherheitshalber ~8).
- Antworten werden einen Tag lang im Ordner ``cache/`` zwischengespeichert.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import requests

from kern.konfig import PROJEKT

CACHE = PROJEKT / "cache"
MIN_ABSTAND = 0.125          # Sekunden zwischen zwei Anfragen -> max. 8 pro Sekunde
CACHE_GUELTIG = 24 * 3600    # Sekunden

_sperre = threading.Lock()
_letzte_anfrage = 0.0


class SecFehler(Exception):
    pass


class SecClient:
    def __init__(self, email: str, app_name: str = "AktienScoring"):
        if not email or "@" not in email:
            raise SecFehler("Keine gültige Kontakt-E-Mail in config/settings.toml eingetragen.")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": f"{app_name} {email}",
            "Accept-Encoding": "gzip, deflate",
        })
        CACHE.mkdir(exist_ok=True)

    def _warten(self):
        global _letzte_anfrage
        with _sperre:
            pause = MIN_ABSTAND - (time.monotonic() - _letzte_anfrage)
            if pause > 0:
                time.sleep(pause)
            _letzte_anfrage = time.monotonic()

    def json(self, url: str, cache_name: str, frisch: bool = False) -> dict:
        datei = CACHE / cache_name
        if not frisch and datei.exists() and time.time() - datei.stat().st_mtime < CACHE_GUELTIG:
            return json.loads(datei.read_text(encoding="utf-8"))
        for versuch in range(4):
            self._warten()
            try:
                antwort = self.session.get(url, timeout=30)
            except requests.RequestException as ex:
                if versuch == 3:
                    raise SecFehler(f"SEC nicht erreichbar: {ex}") from ex
                time.sleep(2 ** versuch)
                continue
            if antwort.status_code == 404:
                raise SecFehler(f"Bei der SEC nicht gefunden: {url}")
            if antwort.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** (versuch + 1))
                continue
            if antwort.status_code == 403:
                raise SecFehler("Die SEC hat die Anfrage abgelehnt (403). Ist die E-Mail in settings.toml korrekt?")
            antwort.raise_for_status()
            daten = antwort.json()
            datei.write_text(json.dumps(daten), encoding="utf-8")
            return daten
        raise SecFehler(f"SEC antwortet nicht (mehrere Versuche): {url}")

    # -------------------------------------------------------------
    def ticker_liste(self) -> dict[str, dict]:
        """Ticker -> {cik, name} aus der offiziellen SEC-Liste."""
        daten = self.json("https://www.sec.gov/files/company_tickers.json", "company_tickers.json")
        return {e["ticker"].upper(): {"cik": int(e["cik_str"]), "name": e["title"]} for e in daten.values()}

    def cik_fuer(self, ticker: str) -> int:
        t = ticker.strip().upper().replace(".", "-")
        liste = self.ticker_liste()
        if t not in liste:
            raise SecFehler(f"Ticker {ticker} ist bei der SEC nicht bekannt.")
        return liste[t]["cik"]

    def submissions(self, cik: int) -> dict:
        return self.json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", f"submissions_{cik}.json")

    def companyfacts(self, cik: int) -> dict:
        return self.json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", f"companyfacts_{cik}.json")
