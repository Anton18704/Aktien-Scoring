"""Gemeinsame Bausteine aller Seiten."""
from __future__ import annotations

import streamlit as st

from kern.konfig import KATEGORIEN, KonfigFehler, lade_schwellen, lade_sektoren, lade_settings
from speicher import db

SEITE_LISTE = "seiten/liste.py"
SEITE_IMPORT = "seiten/import_seite.py"
SEITE_DETAIL = "seiten/detail.py"
SEITE_KATEGORIE = "seiten/kategorie.py"
SEITE_EINSTELLUNGEN = "seiten/einstellungen.py"


@st.cache_resource
def verbindung():
    return db.verbinden()


def schwellen() -> dict:
    try:
        return lade_schwellen()
    except KonfigFehler as ex:
        st.error(f"Fehler in config/schwellen.yaml: {ex}")
        st.stop()


def sektoren() -> list[str]:
    return lade_sektoren()["sektoren"]


def kategorie_namen(s: dict) -> dict[str, str]:
    return {k: f"{k} · {s['kategorien'][k]['name']}" for k in KATEGORIEN}


def einrichtung_pruefen() -> bool:
    settings = lade_settings()
    if not settings or not settings.get("sec", {}).get("email"):
        st.warning("Bitte zuerst einrichten: Auf der Seite **Einstellungen** die Kontakt-E-Mail für die SEC eintragen.")
        st.page_link(SEITE_EINSTELLUNGEN, label="Zu den Einstellungen", icon="⚙️")
        return False
    return True


def zu_detail(ticker: str):
    st.session_state["ticker"] = ticker
    st.switch_page(SEITE_DETAIL)


def zu_kategorie(kategorie: str):
    st.session_state["kategorie"] = kategorie
    st.switch_page(SEITE_KATEGORIE)


def neu_analysieren(ticker: str):
    from analyse import AnalyseFehler, analysieren

    with st.spinner(f"Analysiere {ticker} … (SEC-Daten und Kurse werden geladen)"):
        try:
            ergebnis = analysieren(verbindung(), ticker, frisch=True)
        except AnalyseFehler as ex:
            st.error(str(ex))
            return None
        except Exception as ex:
            st.error(f"Unerwarteter Fehler bei {ticker}: {ex}")
            return None
    st.toast(f"{ergebnis.name} neu analysiert.")
    return ergebnis


def sektor_filter(key: str, alle_werte) -> list[str]:
    optionen = sorted(set(alle_werte))
    return st.multiselect("Sektor", optionen, default=[], key=key, placeholder="Alle Sektoren")
