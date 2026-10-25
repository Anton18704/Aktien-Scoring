import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import auswertung
from kern import dcf as dcf_modell
from kern.format import betrag, prozent, zahl
from kern.konfig import KATEGORIEN, KonfigFehler, lade_dcf
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
try:
    dcf_cfg = auswertung.dcf_konfig(con)
except KonfigFehler as ex:
    st.error(f"Fehler in config/dcf.yaml: {ex}")
    st.stop()
manuell = db.dcf_manuell(con, ticker)
dcf_erg, dcf_ein = auswertung.dcf_berechnen(analyse, t, manuell, s, dcf_cfg)
zeilen = auswertung.mit_dcf(db.kennzahlen_fuer(con, [analyse_id]), analyse, t, manuell, s, dcf_cfg)
gewichte, aktiv = auswertung.gewichte_und_aktiv(con, s)
scores, gesamt = auswertung.bewertung(zeilen, e, s, gewichte, aktiv)

for h in json.loads(analyse["hinweise"] or "[]"):
    st.info(h)

makro, makro_aktiv = auswertung.makro_stand(con)
faktor = auswertung.sektorfaktor(makro, db.sektor(t))
score_makro = auswertung.mit_makro(gesamt.score, faktor, makro_aktiv)
m0, m1, m2 = st.columns([1, 1, 2])
m0.metric("Gesamtscore mit Makro" if faktor and makro_aktiv else "Gesamtscore",
          "–" if score_makro is None else zahl(score_makro, 1) + " / 100")
if faktor:
    from makro_sektoren import lade_makro_cfg
    phase = lade_makro_cfg()["phasen"][faktor["phase"]]["name"]
    m1.metric("ohne Makro", "–" if gesamt.score is None else zahl(gesamt.score, 1),
              help=f"Sektorfaktor {db.sektor(t)}: {faktor.get('text', '')}"
                   + ("" if makro_aktiv else " (Multiplikator in config/makro.yaml ausgeschaltet)"))
    m1.caption(f"Sektor {db.sektor(t)}: Faktor **{zahl(faktor['faktor'], 2)}** · Phase **{phase}**")
    m1.page_link(g.SEITE_SEKTOREN, label="Zur Zyklusuhr", icon="🧭")
else:
    m1.caption("Noch keine Sektorfaktoren – auf der Seite „Sektoren“ die Makrodaten laden.")
    m1.page_link(g.SEITE_SEKTOREN, label="Zu den Sektoren", icon="🧭")
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

# ------------------------------------------------------------ DCF-Bewertung
st.subheader("DCF-Bewertung (Bear / Base / Bull)")
if dcf_erg is None:
    st.info("Diese Analyse stammt aus der Zeit vor dem DCF-Modell. Bitte oben auf „Neu analysieren“ tippen.")
elif dcf_erg.grund:
    st.warning(f"Kein DCF möglich: {dcf_erg.grund}")
else:
    w = dcf_ein.waehrung
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"Fairer Wert, gewichtet ({w})", zahl(dcf_erg.fairer_wert, 2))
    c2.metric(f"Kurs ({w})", zahl(dcf_ein.kurs, 2))
    c3.metric("Sicherheitsmarge", prozent(dcf_erg.sicherheitsmarge),
              help="(fairer Wert – Kurs) ÷ fairer Wert. Positiv = Kurs liegt unter dem fairen Wert.")
    c4.metric("Abstand zum Bear-Wert", "–" if dcf_erg.bear_abstand is None else prozent(dcf_erg.bear_abstand),
              help="Wie weit der Bear-Wert über (+) oder unter (–) dem Kurs liegt.")
    if dcf_erg.bear_abstand is not None and dcf_erg.bear_abstand > 0:
        st.success("Der Kurs liegt sogar unter dem fairen Wert im Bear-Szenario.")
    if dcf_erg.eingepreist_text:
        vergleich = (f" – zum Vergleich: erwartetes Wachstum {prozent(dcf_ein.wachstum)}"
                     if dcf_erg.eingepreistes_wachstum is not None else "")
        st.markdown(f"**Reverse DCF:** {dcf_erg.eingepreist_text}{vergleich}.")
    if dcf_erg.manuell:
        st.caption(f"✏️ Annahmen teilweise manuell gesetzt am {manuell['zeitpunkt'][:10]}"
                   + (f": „{manuell['notiz']}“" if manuell.get("notiz") else ""))

    sz = dcf_erg.szenarien
    namen_sz = [x.name for x in sz.values()]
    werte_sz = [x.fairer_wert or 0 for x in sz.values()]
    fig = go.Figure(go.Bar(x=namen_sz, y=werte_sz, marker_color=["#c0392b", "#7f8c8d", "#27ae60"],
                           text=[f"{zahl(v, 2)}" for v in werte_sz], textposition="auto"))
    fig.add_hline(y=dcf_ein.kurs, line_dash="dash", annotation_text=f"Kurs {zahl(dcf_ein.kurs, 2)}",
                  annotation_position="top left")
    fig.add_hline(y=dcf_erg.fairer_wert, line_dash="dot", line_color="#2c3e50",
                  annotation_text=f"gewichtet {zahl(dcf_erg.fairer_wert, 2)}", annotation_position="bottom right")
    fig.update_layout(title=f"Fairer Wert je Aktie ({w})", height=330, margin=dict(l=10, r=10, t=40, b=20))
    st.plotly_chart(fig, width="stretch")

    annahmen = pd.DataFrame({
        x.name: {
            "Gewicht": prozent(dcf_erg.gewichte.get(n, 0) * 100, 0),
            "Start-FCF": f"{betrag(x.start_fcf, w)} ({ {'ttm': '12 Monate', 'minimum': 'Minimum', 'durchschnitt': 'Durchschnitt', 'manuell': 'manuell ✏️'}.get(x.start_art, x.start_art) })",
            "Wachstum Jahre 1–5": prozent(x.wachstum) + (" ✏️" if x.wachstum_manuell else ""),
            "Langfristiges Wachstum": prozent(x.langfr_wachstum),
            "Abzinsungssatz": prozent(x.abzinsung),
            "Exit-Multiple (Kurs/FCF)": zahl(x.exit_multiple, 1),
            "Endwert-Methode": x.endwert_methode or "–",
            "Anteil Endwert": "–" if x.endwert_anteil is None else prozent(x.endwert_anteil, 0),
            "Fairer Wert je Aktie": "–" if x.fairer_wert is None else f"{zahl(x.fairer_wert, 2)} {w}",
            "Hinweis": x.hinweis or "",
        } for n, x in sz.items()})
    st.dataframe(annahmen, width="stretch")
    st.caption(f"Abzinsung Base = risikofreier Zins {prozent(dcf_ein.zins, 2)} ({dcf_ein.zins_quelle}"
               f"{', ' + dcf_ein.zins_datum if dcf_ein.zins_datum else ''}) + Marktrisikoprämie "
               f"{prozent(float(dcf_cfg['marktrisikopraemie']))} + Branchenzuschlag {dcf_erg.sektor}. "
               f"Nettocash {betrag(dcf_ein.nettocash, w)} (nur positiver Betrag wird addiert). "
               f"Erwartetes Wachstum: {dcf_ein.wachstum_text}. Annahmen ändern in config/dcf.yaml.")

    with st.expander("Empfindlichkeit: fairer Wert (Base) bei anderem Abzinsungssatz und Wachstum"):
        emp = dcf_erg.empfindlichkeit
        # Farbe = Abstand zum Kurs: grün = fairer Wert über dem Kurs, rot = darunter
        abstand = [[(v - dcf_ein.kurs) / dcf_ein.kurs * 100 for v in zeile] for zeile in emp["werte"]]
        fig = go.Figure(go.Heatmap(
            z=abstand, x=[f"Wachstum {prozent(gw)}" for gw in emp["spalten"]],
            y=[f"Abzinsung {prozent(r)}" for r in emp["zeilen"]],
            text=[[zahl(v, 2) for v in zeile] for zeile in emp["werte"]], texttemplate="%{text}",
            colorscale="RdYlGn", zmid=0, showscale=False,
            hovertemplate="%{y}, %{x}: fairer Wert %{text}<extra></extra>"))
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, width="stretch")
        st.caption(f"Fairer Wert je Aktie in {w}. Grün = über dem Kurs von {zahl(dcf_ein.kurs, 2)}, rot = darunter. "
                   "Die Mitte entspricht dem Base-Szenario.")

    with st.expander("✏️ Annahmen von Hand festlegen (Wachstum, normalisierter Free Cashflow)"):
        st.write("Überschreibt die automatischen Werte, z. B. wenn die Vergangenheit durch Sondereffekte verzerrt "
                 "ist. Leer lassen = automatisch. Die Eingabe wird mit Datum gespeichert.")
        fcf_info = ", ".join([f"12 Monate {betrag(dcf_ein.fcf_ttm, w)}"] +
                             [betrag(x, w) for x in dcf_ein.fcf_jahre]) if dcf_ein.fcf_ttm is not None else ""
        with st.form("dcf_manuell"):
            vorschlag_fcf = (manuell or {}).get("start_fcf")
            fcf_text = st.text_input(
                f"Normalisierter Free Cashflow in Mrd. {w} (gilt für alle Szenarien)",
                value="" if vorschlag_fcf is None else zahl(vorschlag_fcf / 1e9, 2),
                placeholder=f"automatisch – zuletzt: {fcf_info}" if fcf_info else "automatisch",
                help="Der Free Cashflow, den die Firma in einem normalen Jahr ohne Sondereffekte erzielt "
                     "(nach Investitionen und Aktienvergütung). Beispiel: 11,5 für 11,5 Mrd.")
            st.markdown("**Wachstum Jahre 1–5 je Szenario (%)**")
            spalten = st.columns(3)
            neu = {}
            for spalte, n in zip(spalten, ("bear", "base", "bull")):
                vorschlag = manuell.get(n) if manuell else None
                auto = dcf_modell.szenario_wachstum(n, dcf_ein.wachstum, dcf_cfg["szenarien"][n],
                                                    float(s["optionen"]["wachstum_min"]),
                                                    float(s["optionen"]["wachstum_max"]))
                neu[n] = spalte.text_input(f"{sz[n].name} (%)", value="" if vorschlag is None else zahl(vorschlag, 1),
                                           placeholder=f"automatisch: {zahl(auto, 1)}")
            notiz = st.text_input("Begründung (optional)", value=(manuell or {}).get("notiz", "") or "")
            k1, k2 = st.columns(2)
            speichern = k1.form_submit_button("Speichern", type="primary")
            zuruecksetzen = k2.form_submit_button("Alle auf automatisch zurücksetzen")
        if speichern:
            try:
                werte = {n: (float(v.replace(",", ".")) if v.strip() else None) for n, v in neu.items()}
                start = float(fcf_text.replace(",", ".")) * 1e9 if fcf_text.strip() else None
            except ValueError:
                st.error("Bitte Zahlen eingeben, z. B. 4,5")
            else:
                if start is not None and start <= 0:
                    st.error("Der normalisierte Free Cashflow muss positiv sein.")
                else:
                    db.dcf_manuell_speichern(con, ticker, werte["bear"], werte["base"], werte["bull"], notiz, start)
                    st.rerun()
        if zuruecksetzen:
            db.dcf_manuell_speichern(con, ticker, None, None, None, "zurückgesetzt")
            st.rerun()

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
st.subheader("Verlauf des Gesamtscores (ohne Makro)")
v = auswertung.verlauf(con, ticker)
if len(v) < 2:
    st.caption("Der Verlauf erscheint ab der zweiten Analyse dieses Titels.")
if not v.empty:
    fig = go.Figure(go.Scatter(x=v["Zeitpunkt"], y=v["Gesamtscore"], mode="lines+markers",
                               text=v["Hinweis"], hovertemplate="%{x|%d.%m.%Y %H:%M}: %{y:.1f}<br>%{text}<extra></extra>"))
    fig.update_layout(yaxis=dict(range=[0, 100], title="Gesamtscore"), height=300, margin=dict(l=10, r=10, t=20, b=30))
    st.plotly_chart(fig, width="stretch")
