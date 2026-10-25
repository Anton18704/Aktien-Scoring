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


def neu_analysieren(ticker: str, still: bool = False):
    from analyse import AnalyseFehler, analysieren

    with st.spinner(f"Analysiere {ticker} … (SEC-Daten und Kurse werden geladen)", show_time=not still):
        try:
            ergebnis = analysieren(verbindung(), ticker, frisch=True)
        except AnalyseFehler as ex:
            st.error(str(ex))
            return None
        except Exception as ex:
            st.error(f"Unerwarteter Fehler bei {ticker}: {ex}")
            return None
    if not still:
        st.toast(f"{ergebnis.name} neu analysiert.")
    return ergebnis


def sektor_filter(key: str, alle_werte) -> list[str]:
    optionen = sorted(set(alle_werte))
    return st.multiselect("Sektor", optionen, default=[], key=key, placeholder="Alle Sektoren")


def tabellen_key(name: str, *filter_werte) -> str:
    """Schlüssel für eine auswählbare Tabelle.

    Ändert sich ein Filter oder wurde etwas gelöscht, entsteht ein neuer Schlüssel.
    Damit wird eine alte Zeilenauswahl verworfen und kann nicht auf einen anderen Titel rutschen.
    """
    version = st.session_state.get(f"{name}_version", 0)
    return f"{name}_{version}_{abs(hash(repr(filter_werte)))}"


def tabelle_zuruecksetzen(name: str) -> None:
    st.session_state[f"{name}_version"] = st.session_state.get(f"{name}_version", 0) + 1


def ausgewaehlte_zeile(auswahl, df):
    """Die ausgewählte Zeile als Series, oder None (auch wenn die Auswahl nicht mehr zur Tabelle passt)."""
    zeilen = auswahl.selection.rows if auswahl and auswahl.selection else []
    if not zeilen or not 0 <= zeilen[0] < len(df):
        return None
    return df.iloc[zeilen[0]]
