import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from kern.format import zahl
from kern.gesamtscore import normierte_gewichte
from kern.konfig import KATEGORIEN, SCHWELLEN_DATEI, lade_settings, schreibe_settings, standardgewichte
from seiten import gemeinsam as g
from speicher import db

st.title("⚙️ Einstellungen")
con = g.verbindung()
s = g.schwellen()
standard = standardgewichte(s)

# ------------------------------------------------------------ Gewichte
st.subheader("Gewichtung der Kategorien")
st.caption("Jede Änderung wirkt sofort auf alle Gesamtscores. Die Gewichte werden automatisch auf 100 % normiert.")

gewichte = db.einstellung(con, "gewichte", standard)
aktiv = db.einstellung(con, "aktiv", {k: True for k in KATEGORIEN})

if st.button("↩️ Standard wiederherstellen (25 / 20 / 15 / 20 / 20)"):
    db.einstellung_setzen(con, "gewichte", standard)
    db.einstellung_setzen(con, "aktiv", {k: True for k in KATEGORIEN})
    for k in KATEGORIEN:
        st.session_state[f"gew_{k}"] = int(standard[k])
        st.session_state[f"aktiv_{k}"] = True
    st.rerun()

for k in KATEGORIEN:
    st.session_state.setdefault(f"aktiv_{k}", bool(aktiv.get(k, True)))
    st.session_state.setdefault(f"gew_{k}", int(gewichte.get(k, standard[k])))

neu_gewichte, neu_aktiv = {}, {}
for k in KATEGORIEN:
    c1, c2 = st.columns([1, 4])
    neu_aktiv[k] = c1.toggle(f"{k} an", key=f"aktiv_{k}")
    neu_gewichte[k] = c2.slider(s["kategorien"][k]["name"], 0, 100, format="%d %%", key=f"gew_{k}",
                                disabled=not neu_aktiv[k])
if neu_gewichte != gewichte or neu_aktiv != aktiv:
    db.einstellung_setzen(con, "gewichte", neu_gewichte)
    db.einstellung_setzen(con, "aktiv", neu_aktiv)

norm = normierte_gewichte(neu_gewichte, neu_aktiv)
if sum(norm.values()) == 0:
    st.error("Alle Gewichte sind 0 oder alle Kategorien ausgeschaltet – es kann kein Gesamtscore berechnet werden.")
else:
    beschriftung = [f"{k} {s['kategorien'][k]['kurz']}" for k in KATEGORIEN]
    fig = go.Figure(go.Bar(x=[norm[k] * 100 for k in KATEGORIEN], y=beschriftung, orientation="h",
                           text=[zahl(norm[k] * 100, 1) + " %" for k in KATEGORIEN], textposition="auto"))
    fig.update_layout(title="Aktuelle Verteilung (normiert)", xaxis=dict(range=[0, 100]),
                      yaxis=dict(autorange="reversed"), height=280, margin=dict(l=10, r=10, t=40, b=20))
    st.plotly_chart(fig, width="stretch")

# ------------------------------------------------------------ Schwellenwerte
st.subheader("Schwellenwerte")
st.caption(f"Ändern in der Datei `config/schwellen.yaml` (mit einem Texteditor, z. B. Notepad). "
           f"Die Änderungen gelten beim nächsten Neuladen der Seite.")
st.dataframe(pd.DataFrame([{
    "Kat.": kz["kategorie"], "Kennzahl": kz["name"], "10 Punkte": kz["zehn"], "5 Punkte": kz["fuenf"],
    "0 Punkte": kz["null"], "Einheit": kz["einheit"], "Berechnung": kz["erklaerung"],
} for kz in s["kennzahlen"].values()]), hide_index=True, width="stretch")

# ------------------------------------------------------------ Einrichtung
st.subheader("Einrichtung")
settings = lade_settings() or {}
with st.form("einrichtung"):
    email = st.text_input("Kontakt-E-Mail für die SEC (Pflicht)", value=settings.get("sec", {}).get("email", ""),
                          help="Die SEC verlangt bei jedem Datenabruf eine Kontaktadresse.")
    tiingo = st.text_input("Tiingo-API-Schlüssel (optional, leer = yfinance)",
                           value=settings.get("kurse", {}).get("tiingo_api_key", ""), type="password")
    if st.form_submit_button("Speichern", type="primary"):
        if "@" not in email:
            st.error("Bitte eine gültige E-Mail-Adresse eingeben.")
        else:
            schreibe_settings(email, tiingo)
            st.success("Gespeichert in config/settings.toml.")
