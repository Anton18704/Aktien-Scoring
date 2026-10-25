"""Aktien-Scoring – Startdatei.

Starten mit:  streamlit run app.py
(oder per Doppelklick auf start.bat unter Windows)
"""
import streamlit as st

st.set_page_config(page_title="Aktien-Scoring", page_icon="📈", layout="wide")

seiten = [
    st.Page("seiten/liste.py", title="Hauptliste", icon="📋", default=True),
    st.Page("seiten/import_seite.py", title="Import", icon="➕"),
    st.Page("seiten/detail.py", title="Detailansicht", icon="🔍"),
    st.Page("seiten/kategorie.py", title="Kategorieansicht", icon="🏷️"),
    st.Page("seiten/sektoren.py", title="Sektoren & Zyklus", icon="🧭"),
    st.Page("seiten/einstellungen.py", title="Einstellungen", icon="⚙️"),
]
st.navigation(seiten).run()
