import pandas as pd
import streamlit as st

from analyse import AnalyseFehler, analysieren, firmen_liste, suche_firmen, tickers_aus_csv
from seiten import gemeinsam as g
from speicher import db

st.title("➕ Import")
if not g.einrichtung_pruefen():
    st.stop()
con = g.verbindung()

st.subheader("Einen Titel hinzufügen")


@st.cache_data(ttl=24 * 3600, show_spinner="Lade die Firmenliste der SEC …")
def _liste():
    return firmen_liste()


def _analysieren(ticker: str):
    with st.spinner(f"Analysiere {ticker} … das dauert einige Sekunden."):
        try:
            erg = analysieren(con, ticker)
        except AnalyseFehler as ex:
            st.error(str(ex))
            return
        except Exception as ex:
            st.error(f"Unerwarteter Fehler: {ex}")
            return
    st.success(f"{erg.name} ({erg.ticker}) analysiert.")
    for h in erg.hinweise:
        st.info(h)
    st.session_state["ticker"] = erg.ticker
    st.page_link(g.SEITE_DETAIL, label=f"Weiter zur Einschätzung von {erg.ticker}", icon="🔍")


begriff = st.text_input("Firmenname oder Ticker", placeholder="z. B. coca cola, general mills, AAPL, BRK.B",
                        help="Groß-/Kleinschreibung egal. Mehrere Wörter: alle müssen im Namen vorkommen.")
if begriff.strip():
    try:
        treffer = suche_firmen(begriff, _liste())
    except AnalyseFehler as ex:
        st.error(str(ex))
        treffer = []
    if not treffer:
        st.warning("Nichts gefunden. Die Liste enthält nur Firmen, die bei der US-Börsenaufsicht SEC berichten.")
    else:
        bekannt = {t["ticker"] for t in db.titel_alle(con)}
        auswahl = st.radio(
            f"{len(treffer)} Treffer{' (die ersten 15)' if len(treffer) == 15 else ''} – bitte auswählen:",
            [t for t, _ in treffer],
            format_func=lambda t: f"{dict(treffer)[t].title()} ({t})" + ("  ✓ schon in der Liste" if t in bekannt else ""),
            key=f"treffer_{begriff}")
        if st.button(f"{auswahl} hinzufügen und analysieren", type="primary"):
            _analysieren(auswahl)

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
