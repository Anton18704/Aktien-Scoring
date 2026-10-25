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


@st.cache_data
def version() -> str:
    """Stand des Codes (letzter Git-Commit), damit man sieht, ob ein Update angekommen ist."""
    import subprocess
    from pathlib import Path
    try:
        return subprocess.run(["git", "log", "-1", "--format=%h · %cd", "--date=format:%d.%m.%Y %H:%M"],
                              cwd=Path(__file__).parent, capture_output=True, text=True, timeout=5).stdout.strip() \
            or "unbekannt (keine Git-Kopie)"
    except Exception:
        return "unbekannt"


st.sidebar.caption(f"Version: {version()}")
st.navigation(seiten).run()
