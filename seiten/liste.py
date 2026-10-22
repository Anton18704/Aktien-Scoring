import streamlit as st

import auswertung
from kern.konfig import KATEGORIEN
from seiten import gemeinsam as g
from speicher import db

st.title("📋 Hauptliste")
g.einrichtung_pruefen()

con = g.verbindung()
s = g.schwellen()
df = auswertung.uebersicht(con)

if df.empty:
    st.info("Noch keine Titel. Füge auf der Seite **Import** einen Ticker hinzu.")
    st.page_link(g.SEITE_IMPORT, label="Zum Import", icon="➕")
    st.stop()

spalte1, spalte2 = st.columns([2, 3])
suche = spalte1.text_input("Suche (Name oder Ticker)", key="liste_suche")
with spalte2:
    gewaehlt = g.sektor_filter("liste_sektor", df["Sektor"])

if suche:
    maske = df["Name"].str.contains(suche, case=False, na=False) | df["Ticker"].str.contains(suche, case=False, na=False)
    df = df[maske]
if gewaehlt:
    df = df[df["Sektor"].isin(gewaehlt)]
df = df.sort_values("Gesamtscore", ascending=False, na_position="last").reset_index(drop=True)

kurz = {k: s["kategorien"][k]["kurz"] for k in KATEGORIEN}
spalten = {
    "Gesamtscore": st.column_config.ProgressColumn("Gesamtscore", min_value=0, max_value=100, format="%.1f"),
    **{kurz[k]: st.column_config.NumberColumn(f"{k} {kurz[k]}", format="%.1f", help=s["kategorien"][k]["name"] + " (0–10)")
       for k in KATEGORIEN},
    "Hinweis": st.column_config.TextColumn("Hinweis", width="medium"),
}
st.caption("Zum Sortieren auf eine Spaltenüberschrift tippen. Eine Zeile antippen, um den Titel auszuwählen.")
auswahl = st.dataframe(df, hide_index=True, width="stretch", column_config=spalten,
                       on_select="rerun", selection_mode="single-row", key="liste_tabelle")

zeilen = auswahl.selection.rows if auswahl and auswahl.selection else []
if zeilen:
    ticker = df.iloc[zeilen[0]]["Ticker"]
    name = df.iloc[zeilen[0]]["Name"]
    st.markdown(f"**Ausgewählt: {name} ({ticker})**")
    b1, b2, b3 = st.columns(3)
    if b1.button("🔍 Details öffnen", type="primary", width="stretch"):
        g.zu_detail(ticker)
    if b2.button("🔄 Neu analysieren", width="stretch"):
        if g.neu_analysieren(ticker):
            st.rerun()
    with b3.popover("🗑️ Löschen", width="stretch"):
        st.write(f"{name} mit allen Analysen und Einschätzungen löschen?")
        if st.button("Ja, endgültig löschen", type="primary"):
            db.titel_loeschen(con, ticker)
            st.rerun()

st.divider()
st.subheader("Kategorieansicht öffnen")
knoepfe = st.columns(len(KATEGORIEN))
for spalte, k in zip(knoepfe, KATEGORIEN):
    if spalte.button(f"{k} · {kurz[k]}", width="stretch"):
        g.zu_kategorie(k)
