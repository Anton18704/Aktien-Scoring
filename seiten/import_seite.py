import pandas as pd
import streamlit as st

from analyse import AnalyseFehler, analysieren, tickers_aus_csv
from seiten import gemeinsam as g

st.title("➕ Import")
if not g.einrichtung_pruefen():
    st.stop()
con = g.verbindung()

st.subheader("Einen Titel hinzufügen")
with st.form("einzel"):
    ticker = st.text_input("Ticker (z. B. AAPL, KO, CAT, BRK.B)")
    los = st.form_submit_button("Hinzufügen und analysieren", type="primary")
if los and ticker.strip():
    with st.spinner(f"Analysiere {ticker.upper()} … das dauert einige Sekunden."):
        try:
            erg = analysieren(con, ticker)
        except AnalyseFehler as ex:
            st.error(str(ex))
            erg = None
        except Exception as ex:
            st.error(f"Unerwarteter Fehler: {ex}")
            erg = None
    if erg:
        st.success(f"{erg.name} ({erg.ticker}) analysiert.")
        for h in erg.hinweise:
            st.info(h)
        st.session_state["ticker"] = erg.ticker
        st.page_link(g.SEITE_DETAIL, label=f"Weiter zur Einschätzung von {erg.ticker}", icon="🔍")

st.divider()
st.subheader("Mehrere Titel per CSV-Datei")
st.caption("Die Datei braucht eine Spalte mit der Überschrift **Ticker**, darunter ein Ticker pro Zeile.")
datei = st.file_uploader("CSV-Datei auswählen", type=["csv", "txt"])
if datei is not None:
    try:
        tickers = tickers_aus_csv(datei)
    except AnalyseFehler as ex:
        st.error(str(ex))
        tickers = []
    except Exception as ex:
        st.error(f"Die Datei konnte nicht gelesen werden: {ex}")
        tickers = []
    if tickers:
        st.write(f"{len(tickers)} Ticker gefunden: {', '.join(tickers)}")
        if st.button(f"Alle {len(tickers)} importieren und analysieren", type="primary"):
            fortschritt = st.progress(0.0)
            protokoll = []
            for i, t in enumerate(tickers, start=1):
                fortschritt.progress(i / len(tickers), text=f"{t} ({i} von {len(tickers)})")
                try:
                    erg = analysieren(con, t)
                    protokoll.append({"Ticker": t, "Ergebnis": "✅ " + erg.name, "Hinweise": " | ".join(erg.hinweise)})
                except Exception as ex:
                    protokoll.append({"Ticker": t, "Ergebnis": "❌ Fehler", "Hinweise": str(ex)})
            st.dataframe(pd.DataFrame(protokoll), hide_index=True, width="stretch")
            st.info("Die persönliche Einschätzung (Kategorie E) ist bei neuen Titeln noch offen. "
                    "Du kannst sie in der Detailansicht nachholen.")
