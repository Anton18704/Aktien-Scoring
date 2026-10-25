import streamlit as st

import auswertung
from kern.konfig import KATEGORIEN
from seiten import gemeinsam as g

st.title("🏷️ Kategorieansicht")
con = g.verbindung()
s = g.schwellen()
namen = g.kategorie_namen(s)

start = st.session_state.get("kategorie", "A")
kategorie = st.radio("Kategorie", KATEGORIEN, index=KATEGORIEN.index(start) if start in KATEGORIEN else 0,
                     format_func=namen.get, horizontal=True)
st.session_state["kategorie"] = kategorie

df = auswertung.kategorie_ansicht(con, kategorie)
if df.empty:
    st.info("Noch keine Titel vorhanden.")
    st.stop()

gewaehlt = g.sektor_filter("kat_sektor", df["Sektor"])
if gewaehlt:
    df = df[df["Sektor"].isin(gewaehlt)]
df = df.reset_index(drop=True)

if kategorie != "E":
    with st.expander("Was bedeuten die Spalten?"):
        for kz in s["kennzahlen"].values():
            if kz["kategorie"] == kategorie:
                st.markdown(f"**{kz['name']}:** {kz['erklaerung']} – 10 / 5 / 0 Punkte bei "
                            f"{kz['zehn']:g} / {kz['fuenf']:g} / {kz['null']:g} {kz['einheit']}")

auswahl = st.dataframe(df, hide_index=True, width="stretch", on_select="rerun",
                       selection_mode="single-row", key=g.tabellen_key("kategorie", kategorie, gewaehlt),
                       column_config={"Kategorie-Score": st.column_config.ProgressColumn(
                           "Kategorie-Score", min_value=0, max_value=10, format="%.1f")})
zeile = g.ausgewaehlte_zeile(auswahl, df)
if zeile is not None:
    ticker = zeile["Ticker"]
    if st.button(f"🔍 Details zu {ticker} öffnen", type="primary"):
        g.zu_detail(ticker)
