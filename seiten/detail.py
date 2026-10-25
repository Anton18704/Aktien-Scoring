import json

import plotly.graph_objects as go
import streamlit as st

import auswertung
from kern.format import zahl
from kern.konfig import KATEGORIEN
from seiten import gemeinsam as g
from speicher import db

FRAGEN = [
    "1. Verstehe ich das Geschäft wirklich?",
    "2. Vertraue ich dem Management?",
    "3. Würde ich die Aktie 10 Jahre halten, wenn die Börse so lange schließen würde?",
    "4. Wie sicher bin ich, dass die Firma in 10 Jahren größer ist?",
]

st.title("🔍 Detailansicht")
con = g.verbindung()
s = g.schwellen()
titel_liste = db.titel_alle(con)
if not titel_liste:
    st.info("Noch keine Titel vorhanden.")
    st.page_link(g.SEITE_IMPORT, label="Zum Import", icon="➕")
    st.stop()

tickers = [t["ticker"] for t in titel_liste]
start = st.session_state.get("ticker") or st.query_params.get("ticker")
index = tickers.index(start) if start in tickers else 0
namen = {t["ticker"]: f"{t['name']} ({t['ticker']})" for t in titel_liste}
ticker = st.selectbox("Titel", tickers, index=index, format_func=namen.get)
st.session_state["ticker"] = ticker
st.query_params["ticker"] = ticker
t = db.titel(con, ticker)

analysen = db.analysen_fuer(con, ticker)
if not analysen:
    st.warning("Für diesen Titel gibt es noch keine Analyse.")
    st.stop()

# ------------------------------------------------------------ Kopf mit Sektor
k1, k2, k3 = st.columns([2, 2, 1])
k1.markdown(f"### {t['name']}\n**Ticker:** {ticker} · **CIK:** {t['cik']} · **Währung:** {t['waehrung']}")
optionen = ["(automatisch)"] + g.sektoren()
aktuell = t["sektor_manuell"] or "(automatisch)"
neu = k2.selectbox(f"Sektor (automatisch: {t['sektor_auto'] or 'unbekannt'}, SIC {t['sic']} {t['sic_beschreibung'] or ''})",
                   optionen, index=optionen.index(aktuell) if aktuell in optionen else 0)
if neu != aktuell:
    db.sektor_manuell_setzen(con, ticker, None if neu == "(automatisch)" else neu)
    st.rerun()
with k3:
    if st.button("🔄 Neu analysieren", width="stretch"):
        if g.neu_analysieren(ticker):
            st.rerun()
    with st.popover("🗑️ Löschen", width="stretch"):
        if st.button("Ja, endgültig löschen", type="primary"):
            db.titel_loeschen(con, ticker)
            st.session_state.pop("ticker", None)
            st.switch_page(g.SEITE_LISTE)

# ------------------------------------------------------------ Einschätzung zuerst
einschaetzungen = db.einschaetzungen_fuer(con, ticker)
letzte_e = einschaetzungen[-1] if einschaetzungen else None
zeigen_key = f"ohne_e_{ticker}"


def einschaetzung_formular(vorlage, schluessel):
    with st.form(schluessel):
        werte = [st.slider(f, 0, 10, int(vorlage[f"f{i + 1}"]) if vorlage else 5, key=f"{schluessel}_{i}")
                 for i, f in enumerate(FRAGEN)]
        begruendung = st.text_input("Begründung in einem Satz (Pflichtfeld)",
                                    value=vorlage["begruendung"] if vorlage else "")
        gegenthese = st.text_input(
            "Ich liege falsch, wenn … (Pflichtfeld)", value=(vorlage.get("gegenthese") or "") if vorlage else "",
            help="Was müsste passieren, damit deine Einschätzung falsch ist? Z. B. 'die Marge zwei Jahre "
                 "in Folge sinkt' oder 'der Marktanteil in China unter 15 % fällt'. In einem Jahr kannst du "
                 "prüfen, ob es eingetreten ist.")
        if st.form_submit_button("Einschätzung speichern", type="primary"):
            if not begruendung.strip() or not gegenthese.strip():
                st.error("Bitte beide Textfelder ausfüllen.")
                return
            db.einschaetzung_speichern(con, ticker, *werte, begruendung, gegenthese)
            st.rerun()


if letzte_e is None and not st.session_state.get(zeigen_key):
    st.subheader("Persönliche Einschätzung")
    st.write("Bitte zuerst deine eigene Einschätzung abgeben. Die Scores werden danach angezeigt, "
             "damit die Zahlen dein Urteil nicht beeinflussen.")
    einschaetzung_formular(None, "e_neu")
    if st.button("Überspringen und Scores trotzdem anzeigen"):
        st.session_state[zeigen_key] = True
        st.rerun()
    st.stop()

# ------------------------------------------------------------ Analyse wählen
beschriftung = {a["id"]: a["zeitpunkt"].replace("T", " ")[:16] for a in analysen}
analyse_id = st.selectbox("Analyse vom", [a["id"] for a in reversed(analysen)], format_func=beschriftung.get)
analyse = next(a for a in analysen if a["id"] == analyse_id)
gueltige_e = dict(zip([a["id"] for a in analysen], auswertung.einschaetzung_fuer_analysen(analysen, einschaetzungen)))
e = gueltige_e[analyse_id]
zeilen = db.kennzahlen_fuer(con, [analyse_id])
gewichte, aktiv = auswertung.gewichte_und_aktiv(con, s)
scores, gesamt = auswertung.bewertung(zeilen, e, s, gewichte, aktiv)

for h in json.loads(analyse["hinweise"] or "[]"):
    st.info(h)

m1, m2 = st.columns([1, 3])
m1.metric("Gesamtscore", "–" if gesamt.score is None else zahl(gesamt.score, 1) + " / 100")
markierung = auswertung.markierung(gesamt, s)
if gesamt.ko:
    m2.error(f"{markierung}\n\nMindestens eine Kategorie liegt unter {zahl(s['optionen']['ko_schwelle'], 1)} Punkten. "
             "Der Score kann das durch Stärken in anderen Kategorien überdecken – bitte genau prüfen.")
elif markierung:
    m2.warning(markierung)

# ------------------------------------------------------------ Diagramme
namen_kat = [f"{k} {s['kategorien'][k]['kurz']}" for k in KATEGORIEN]
d1, d2 = st.columns(2)
with d1:
    werte = [scores[k] if scores[k] is not None else 0 for k in KATEGORIEN]
    text = [zahl(scores[k]) if scores[k] is not None else "fehlt" for k in KATEGORIEN]
    fig = go.Figure(go.Scatterpolar(r=werte + werte[:1], theta=namen_kat + namen_kat[:1], fill="toself",
                                    text=text + text[:1], hovertemplate="%{theta}: %{text}<extra></extra>"))
    fig.update_layout(polar=dict(radialaxis=dict(range=[0, 10], tickvals=[0, 2.5, 5, 7.5, 10])),
                      title="Kategorie-Scores (0–10)", showlegend=False, height=380, margin=dict(l=40, r=40, t=50, b=30))
    st.plotly_chart(fig, width="stretch")
with d2:
    beitraege = [gesamt.beitraege.get(k, 0) for k in KATEGORIEN]
    gew = [gesamt.verwendete_gewichte.get(k, 0) * 100 for k in KATEGORIEN]
    fig = go.Figure(go.Bar(x=beitraege, y=namen_kat, orientation="h",
                           text=[f"{zahl(b)} Pkt. (Gewicht {zahl(w, 0)} %)" for b, w in zip(beitraege, gew)],
                           textposition="auto"))
    fig.update_layout(title="Beitrag zum Gesamtscore (Score × Gewicht)", xaxis=dict(range=[0, max(30, max(beitraege) * 1.2)]),
                      yaxis=dict(autorange="reversed"), height=380, margin=dict(l=10, r=10, t=50, b=30))
    st.plotly_chart(fig, width="stretch")

# ------------------------------------------------------------ Kennzahlen je Kategorie
st.subheader("Kennzahlen")
for k in KATEGORIEN:
    titel = f"{k} · {s['kategorien'][k]['name']} – Score {zahl(scores[k]) if scores[k] is not None else 'fehlt'}"
    with st.expander(titel, expanded=(k != "E")):
        if k == "E":
            if e:
                for i, f in enumerate(FRAGEN):
                    st.write(f"{f} **{zahl(e[f'f{i + 1}'], 0)}**")
                st.write(f"Begründung: _{e['begruendung']}_ (vom {e['zeitpunkt'][:10]})")
                st.write(f"Ich liege falsch, wenn: _{e.get('gegenthese') or '– (noch nicht angegeben)'}_")
            else:
                st.write("Einschätzung offen.")
            st.markdown("**Einschätzung neu abgeben** (ältere bleiben im Verlauf erhalten)")
            einschaetzung_formular(letzte_e, "e_aendern")
        else:
            tabelle = auswertung.kennzahlen_tabelle(zeilen, s, k)
            st.dataframe(tabelle, hide_index=True, width="stretch",
                         column_config={"Quelle": st.column_config.TextColumn(width="large"),
                                        "Rechenweg": st.column_config.TextColumn(width="large")})

# ------------------------------------------------------------ Verlauf
st.subheader("Verlauf des Gesamtscores")
v = auswertung.verlauf(con, ticker)
if len(v) < 2:
    st.caption("Der Verlauf erscheint ab der zweiten Analyse dieses Titels.")
if not v.empty:
    fig = go.Figure(go.Scatter(x=v["Zeitpunkt"], y=v["Gesamtscore"], mode="lines+markers",
                               text=v["Hinweis"], hovertemplate="%{x|%d.%m.%Y %H:%M}: %{y:.1f}<br>%{text}<extra></extra>"))
    fig.update_layout(yaxis=dict(range=[0, 100], title="Gesamtscore"), height=300, margin=dict(l=10, r=10, t=20, b=30))
    st.plotly_chart(fig, width="stretch")
