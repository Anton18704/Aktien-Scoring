"""Lädt die Konfigurationsdateien (Schwellenwerte, Sektoren, persönliche Einstellungen)."""
from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

PROJEKT = Path(__file__).resolve().parent.parent
CONFIG = PROJEKT / "config"
SCHWELLEN_DATEI = CONFIG / "schwellen.yaml"
SEKTOREN_DATEI = CONFIG / "sic_sektoren.yaml"
SETTINGS_DATEI = CONFIG / "settings.toml"
DCF_DATEI = CONFIG / "dcf.yaml"

KATEGORIEN = ["A", "B", "C", "D", "E"]


class KonfigFehler(Exception):
    pass


def lade_schwellen(pfad: Path = SCHWELLEN_DATEI) -> dict:
    """Liest schwellen.yaml und prüft, ob die Werte zueinander passen."""
    with open(pfad, encoding="utf-8") as f:
        daten = yaml.safe_load(f)
    for schluessel, k in daten["kennzahlen"].items():
        try:
            zehn, fuenf, null = float(k["bei_10"]), float(k["bei_5"]), float(k["bei_0"])
        except (KeyError, TypeError, ValueError):
            raise KonfigFehler(f"{schluessel}: 'bei_10', 'bei_5' und 'bei_0' müssen Zahlen sein.")
        if zehn == null:
            raise KonfigFehler(f"{schluessel}: 'bei_10' und 'bei_0' dürfen nicht gleich sein.")
        if not (min(zehn, null) <= fuenf <= max(zehn, null)):
            raise KonfigFehler(f"{schluessel}: 'bei_5' muss zwischen 'bei_10' und 'bei_0' liegen.")
        k["zehn"], k["fuenf"], k["null"] = zehn, fuenf, null
        if k["kategorie"] not in KATEGORIEN:
            raise KonfigFehler(f"{schluessel}: unbekannte Kategorie {k['kategorie']}.")
    daten["optionen"] = {**OPTIONEN_STANDARD, **(daten.get("optionen") or {})}
    return daten


OPTIONEN_STANDARD = {
    "fcf_abzug_aktienverguetung": True,
    "ko_schwelle": 3.0,
    "wachstum_min": -5.0,
    "wachstum_max": 12.0,
}


def kennzahlen_der_kategorie(schwellen: dict, kategorie: str) -> list[str]:
    return [s for s, k in schwellen["kennzahlen"].items() if k["kategorie"] == kategorie]


def standardgewichte(schwellen: dict) -> dict[str, float]:
    return {k: float(v["standardgewicht"]) for k, v in schwellen["kategorien"].items()}


def lade_sektoren(pfad: Path = SEKTOREN_DATEI) -> dict:
    with open(pfad, encoding="utf-8") as f:
        return yaml.safe_load(f)


def sektor_fuer_sic(sic, sektoren: dict | None = None) -> str | None:
    """Ordnet einen SIC-Code einem der 11 Sektoren zu (erste passende Regel gewinnt)."""
    if sic in (None, ""):
        return None
    try:
        code = int(sic)
    except (TypeError, ValueError):
        return None
    sektoren = sektoren or lade_sektoren()
    for regel in sektoren["regeln"]:
        if regel["von"] <= code <= regel["bis"]:
            return regel["sektor"]
    return None


def lade_settings(pfad: Path = SETTINGS_DATEI) -> dict | None:
    """Liest settings.toml. Gibt None zurück, wenn die Datei noch fehlt."""
    if not pfad.exists():
        return None
    with open(pfad, "rb") as f:
        return tomllib.load(f)


def schreibe_settings(email: str, tiingo_key: str = "", pfad: Path = SETTINGS_DATEI) -> None:
    """Legt settings.toml an. Wird von der Einrichtungsseite der App aufgerufen."""
    email = email.strip().replace('"', "")
    tiingo_key = tiingo_key.strip().replace('"', "")
    inhalt = (
        "# Persönliche Einstellungen. Diese Datei wird NICHT zu GitHub hochgeladen.\n\n"
        "[sec]\n"
        "# Die SEC verlangt eine Kontakt-E-Mail im User-Agent jeder Anfrage.\n"
        f'email = "{email}"\n'
        'app_name = "AktienScoring"\n\n'
        "[kurse]\n"
        "# Leer lassen = yfinance (Yahoo Finance). Mit Tiingo-Schlüssel wird Tiingo bevorzugt.\n"
        f'tiingo_api_key = "{tiingo_key}"\n'
    )
    pfad.write_text(inhalt, encoding="utf-8")


def lade_dcf(pfad: Path = DCF_DATEI) -> dict:
    """Liest dcf.yaml (Szenarien, Branchen-Multiplikatoren, Zinsquelle)."""
    with open(pfad, encoding="utf-8") as f:
        daten = yaml.safe_load(f)
    for name in ("bear", "base", "bull"):
        if name not in daten.get("szenarien", {}):
            raise KonfigFehler(f"dcf.yaml: Szenario '{name}' fehlt.")
    if "unbekannt" not in daten.get("branchen", {}):
        raise KonfigFehler("dcf.yaml: Branche 'unbekannt' fehlt (wird für Titel ohne Sektor gebraucht).")
    return daten
