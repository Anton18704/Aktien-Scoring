from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from kern.format import prozent, zahl
from seiten import gemeinsam as g
from makro_sektoren import (aktualisieren, gespeichert, lade_makro_cfg, letzter_pruefstand, pruefstand,
                            regeln_kennung, rekonstruieren)
from speicher import db

st.title("🧭 Sektoren & Zyklus")
st.caption("Antizyklisch: Der Faktor ist am höchsten, wenn die Lage eines Sektors noch schlecht ist, sich aber "
           "bessert (Erholung), und am niedrigsten, wenn alles glänzt, die Daten aber drehen (Boom/Wende). "
           "Der Gesamtscore jeder Aktie wird mit dem Faktor ihres Sektors multipliziert.")

con = g.verbindung()
cfg = lade_makro_cfg()
phasen = cfg["phasen"]
daten = gespeichert(con)

k1, k2 = st.columns([3, 1])
if daten:
    alter = datetime.now() - datetime.fromisoformat(daten["stand"])
    k1.write(f"Stand der Makrodaten: **{daten['stand'][:16].replace('T', ' ')}** "
             f"({'heute' if alter.days == 0 else f'vor {alter.days} Tagen'})")
if k2.button("🔄 Makrodaten aktualisieren", type="primary" if not daten else "secondary", width="stretch") or not daten:
    with st.spinner("Lade Indikatoren (FRED), Sektor-ETFs (Yahoo) und Branchendaten (Damodaran) … ca. 1 Minute"):
        daten = aktualisieren(con)
    st.rerun()
test = letzter_pruefstand(con)
if not cfg.get("aktiv", True):
    st.info("**Nur zur Information:** Der Multiplikator ist in config/makro.yaml ausgeschaltet – die Faktoren "
            "verändern keine Scores. Grund: Der Prüfstand (unten) zeigt bisher keine Vorhersagekraft.")
elif test and not test.get("bestanden"):
    st.error("Achtung: Der Multiplikator ist eingeschaltet, obwohl die Regeln den Prüfstand nicht bestehen. "
             "Empfehlung: in config/makro.yaml `aktiv: false` setzen.")
for h in daten.get("hinweise", []):
    st.warning(h)

sektoren = daten["sektoren"]

# ------------------------------------------------------------ Zyklusuhr
GRENZE = 2.5


def uhr(hoehe=520):
    """Leere Zyklusuhr mit den vier farbigen Phasen."""
    f = go.Figure()
    for (x0, x1, y0, y1, phase) in ((0, GRENZE, -GRENZE, 0, "erholung"), (0, GRENZE, 0, GRENZE, "aufschwung"),
                                    (-GRENZE, 0, 0, GRENZE, "boom"), (-GRENZE, 0, -GRENZE, 0, "abschwung")):
        f.add_shape(type="rect", x0=x0, x1=x1, y0=y0, y1=y1, fillcolor=phasen[phase]["farbe"], opacity=0.12,
                    line_width=0, layer="below")
        f.add_annotation(x=(x0 + x1) / 2, y=y1 * 0.92 if y1 > 0 else y0 * 0.92,
                         text=f"<b>{phasen[phase]['name']}</b> · Faktor {zahl(phasen[phase]['faktor'], 2)}",
                         showarrow=False, font=dict(color=phasen[phase]["farbe"], size=12))
    f.update_layout(height=hoehe, showlegend=False, margin=dict(l=10, r=10, t=10, b=10),
                    xaxis=dict(range=[-GRENZE, GRENZE], title="Richtung: verschlechtert sich ← → verbessert sich",
                               zeroline=True, zerolinewidth=2),
                    yaxis=dict(range=[-GRENZE, GRENZE], title="Niveau: schlechter ↓ ↑ besser als üblich",
                               zeroline=True, zerolinewidth=2))
    return f


def begrenzt(v):
    return max(-GRENZE, min(GRENZE, v))


st.subheader("Zyklusuhr")
grenze = GRENZE
fig = uhr()
mit_daten = {n: s for n, s in sektoren.items() if s["niveau"] is not None and s["richtung"] is not None}
if mit_daten:
    fig.add_trace(go.Scatter(
        x=[max(-grenze, min(grenze, s["richtung"])) for s in mit_daten.values()],
        y=[max(-grenze, min(grenze, s["niveau"])) for s in mit_daten.values()],
        mode="markers+text", text=[f"{n} {zahl(s['faktor'], 2)}" for n, s in mit_daten.items()],
        textposition="top center",
        marker=dict(size=14, color=[phasen[s["phase"]]["farbe"] for s in mit_daten.values()],
                    line=dict(width=1, color="#333")),
        hovertemplate="%{text}<br>Richtung %{x:.2f}, Niveau %{y:.2f}<extra></extra>"))
st.plotly_chart(fig, width="stretch")
if len(mit_daten) < len(sektoren):
    st.caption(f"{len(sektoren) - len(mit_daten)} Sektoren ohne Makrodaten (Phase neutral, nicht in der Uhr): "
               + ", ".join(n for n in sektoren if n not in mit_daten))

# ------------------------------------------------------------ Übersicht
st.subheader("Übersicht")
uebersicht = pd.DataFrame([{
    "Sektor": n, "Phase": phasen[s["phase"]]["name"], "Faktor": round(s["faktor"], 2),
    "Grundfaktor": s["grundfaktor"], "Bewertung": round(s["bonus"], 3),
    "Niveau": None if s["niveau"] is None else round(s["niveau"], 2),
    "Richtung": None if s["richtung"] is None else round(s["richtung"], 2),
    "Sektor-KGV": None if s["kgv"] is None else round(s["kgv"], 1),
    "Beta": None if s["beta"] is None else round(s["beta"], 2),
    "ETF vs. Trend": None if s["etf_abweichung"] is None else f"{s['etf']} {prozent(s['etf_abweichung'], 0)}",
} for n, s in sorted(sektoren.items(), key=lambda x: -x[1]["faktor"])])
st.dataframe(uebersicht, hide_index=True, width="stretch",
             column_config={"Faktor": st.column_config.ProgressColumn(
                 "Faktor", min_value=cfg["faktor_min"], max_value=cfg["faktor_max"], format="%.2f")})


# ------------------------------------------------------------ Verlauf
st.subheader("Verlauf")
verlauf = pd.DataFrame(db.sektor_verlauf(con))
rekonstruiert = not verlauf.empty and (verlauf["quelle"] == "rekonstruiert").any()
v1, v2 = st.columns([3, 1])
v1.caption("Jede Aktualisierung wird gespeichert (live). Zusätzlich lässt sich der Verlauf der letzten 3 Jahre aus "
           "den historischen Daten nachrechnen – dabei werden je Monat nur Daten verwendet, die damals schon "
           "veröffentlicht waren (ein Monat Verzug). Hinweis: FRED liefert teils nachträglich korrigierte Werte.")
if v2.button("🕰️ Letzte 3 Jahre nachrechnen" if not rekonstruiert else "🕰️ Nachrechnung erneuern", width="stretch"):
    with st.spinner("Rechne 36 Monate nach … (Daten sind meist schon zwischengespeichert)"):
        anzahl = rekonstruieren(con)
    st.toast(f"{anzahl} Monate nachgerechnet.")
    st.rerun()

if verlauf.empty or verlauf["monat"].nunique() < 2:
    st.info("Für einen Verlauf braucht es mindestens zwei Monate. Tippe auf „Letzte 3 Jahre nachrechnen“ "
            "oder aktualisiere die Makrodaten in den kommenden Wochen erneut.")
else:
    verlauf["Monat"] = pd.to_datetime(verlauf["monat"] + "-01")
    alle = sorted(verlauf["sektor"].unique())
    eigene = sorted({db.sektor(t) for t in db.titel_alle(con)} & set(alle))
    auswahl_v = st.multiselect("Sektoren im Diagramm", alle, default=eigene or alle[:3], key="verlauf_sektoren",
                               help="Vorausgewählt sind die Sektoren deiner Titel aus der Hauptliste.")
    fig = go.Figure()
    for n in auswahl_v:
        d = verlauf[verlauf["sektor"] == n].sort_values("Monat")
        fig.add_trace(go.Scatter(
            x=d["Monat"], y=d["faktor"], mode="lines+markers", name=n, line_shape="hv",
            text=[f"{phasen[p]['name']} ({q})" for p, q in zip(d["phase"], d["quelle"])],
            hovertemplate=f"{n} %{{x|%m/%Y}}: Faktor %{{y:.2f}}<br>%{{text}}<extra></extra>"))
    fig.add_hline(y=1.0, line_dash="dot", line_color="#555")
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(title="Sektorfaktor"),
                      legend=dict(orientation="h", y=-0.15))
    st.plotly_chart(fig, width="stretch")

    st.markdown("**Weg eines Sektors durch die Zyklusuhr**")
    p1, p2 = st.columns([2, 1])
    sektor_pfad = p1.selectbox("Sektor", alle, key="pfad_sektor")
    monate_pfad = p2.select_slider("Zeitraum", options=[6, 12, 24, 36], value=12, format_func=lambda m: f"{m} Monate")
    d = verlauf[(verlauf["sektor"] == sektor_pfad)].dropna(subset=["niveau", "richtung"]).sort_values("Monat")
    d = d.tail(monate_pfad)
    if len(d) >= 2:
        fig = uhr(hoehe=480)
        fig.add_trace(go.Scatter(
            x=[begrenzt(v) for v in d["richtung"]], y=[begrenzt(v) for v in d["niveau"]],
            mode="lines+markers", line=dict(color="#2c3e50", width=2),
            marker=dict(size=[6] * (len(d) - 1) + [16], color=[phasen[p]["farbe"] for p in d["phase"]],
                        line=dict(width=1, color="#333")),
            text=[f"{m:%m/%Y}: {phasen[p]['name']}, Faktor {zahl(f, 2)}" for m, p, f in zip(d["Monat"], d["phase"], d["faktor"])],
            hovertemplate="%{text}<extra></extra>"))
        for i in (0, len(d) - 1):
            fig.add_annotation(x=begrenzt(d["richtung"].iloc[i]), y=begrenzt(d["niveau"].iloc[i]),
                               text=("Start " if i == 0 else "jetzt ") + f"{d['Monat'].iloc[i]:%m/%Y}",
                               showarrow=True, arrowhead=0, ax=30, ay=-25)
        st.plotly_chart(fig, width="stretch")
        st.caption("Ein typischer Zyklus läuft gegen den Uhrzeigersinn: Erholung → Aufschwung → Boom/Wende → "
                   "Abschwung → Erholung. Der große Punkt ist der aktuelle Stand.")
    else:
        st.caption("Für diesen Sektor gibt es noch zu wenige Monate mit Daten.")

# ------------------------------------------------------------ Prüfstand
st.subheader("🧪 Prüfstand")
st.caption("Rechnet die Sektorfaktoren für jeden Monat seit 2008 genau so nach, wie die App sie heute berechnet "
           "(nur damals veröffentlichte Daten, Glättung, Bestätigung, Bewertungsbonus), und vergleicht sie mit der "
           "Rendite der Sektor-ETFs in den folgenden 12 Monaten relativ zum S&P 500. Nach jeder Änderung an "
           "config/makro.yaml erneut starten.")
if st.button("🧪 Prüfstand starten (ca. 1 Minute)"):
    balken = st.progress(0.0, text="Rechne Monate nach …")
    test = pruefstand(con, fortschritt=lambda x: balken.progress(x, text=f"Rechne Monate nach … {x * 100:.0f} %"))
    st.rerun()
if not test:
    st.info("Noch kein Prüfstand gelaufen.")
elif test.get("grund"):
    st.warning(f"Prüfstand nicht möglich: {test['grund']}")
else:
    if test.get("regeln") != regeln_kennung():
        st.warning("Die Regeln in config/makro.yaml wurden seit diesem Test geändert – bitte erneut starten.")
    (st.success if test["bestanden"] else st.error)(
        f"**{'Bestanden' if test['bestanden'] else 'Nicht bestanden'}** – Test vom {test['stand'][:10]}, "
        f"{test['anzahl']} Sektor-Monate {test['von']}–{test['bis']}, Korrelation Faktor ↔ Rendite "
        f"{zahl(test['korrelation'], 3)}")
    for pr in test["pruefungen"]:
        st.markdown(f"{'✅' if pr['ok'] else '❌'} {pr['text']}")
    tab = pd.DataFrame([{
        "Phase": d["name"], "Faktor": d["faktor"], "Sektor-Monate": d["anzahl"],
        "Ø Rendite vs. S&P 500 (12 M)": None if d["mittel"] is None else round(d["mittel"], 1),
        "Median": None if d["median"] is None else round(d["median"], 1),
        "Markt geschlagen": None if d["treffer"] is None else f"{d['treffer']:.0f} %",
    } for d in test["je_phase"].values()])
    st.dataframe(tab, hide_index=True, width="stretch")
    h = test["haelften"]
    st.caption(
        f"Erste Hälfte ({h['erste']['von']}–{h['erste']['bis']}): Faktor > 1 im Schnitt "
        f"{prozent(h['erste']['faktor_hoch'])}, Faktor < 1 {prozent(h['erste']['faktor_tief'])}. "
        f"Zweite Hälfte ({h['zweite']['von']}–{h['zweite']['bis']}): {prozent(h['zweite']['faktor_hoch'])} vs. "
        f"{prozent(h['zweite']['faktor_tief'])}. Alle Werte relativ zum S&P 500 – dass sie meist negativ sind, liegt "
        "an der Stärke der großen Tech-Werte im Index; entscheidend sind die Unterschiede zwischen den Phasen. "
        "Grenzen: überlappende 12-Monats-Zeiträume (weniger unabhängige Beobachtungen als es scheint), teils "
        "nachträglich korrigierte FRED-Daten, Sektor-ETFs statt Einzelaktien.")

# ------------------------------------------------------------ Karten je Sektor
def ampel(z):
    if z is None:
        return "–"
    return "🟢" if z > 0.5 else "🔴" if z < -0.5 else "🟡"


def pfeil(z):
    if z is None:
        return "–"
    return "↑" if z > 0.25 else "↓" if z < -0.25 else "→"


st.subheader("Sektoren im Detail")
for n, s in sorted(sektoren.items(), key=lambda x: -x[1]["faktor"]):
    with st.expander(f"{n} – {phasen[s['phase']]['name']} – Faktor {zahl(s['faktor'], 2)}"):
        st.markdown(f"**Rechnung:** {s.get('text', '')}")
        if s.get("hinweis"):
            st.info(s["hinweis"])
        zeilen = []
        for i in s["indikatoren"]:
            einheit = "%" if i.get("wert") is not None and cfg["indikatoren"].get(i["id"], {}).get(
                "umrechnung") == "jahresrate" or "differenz" in cfg["indikatoren"].get(i["id"], {}) else ""
            zeilen.append({
                "Indikator": i["name"] + (" (ggü. Vorjahr)" if einheit else ""),
                "Aktuell": "–" if i["wert"] is None else f"{zahl(i['wert'], 2)}{' %' if einheit else ''}",
                "Stand (Monat)": (i["datum"] or "")[:7],
                "Gut, wenn": i["gut_wenn"],
                "Niveau für Sektor": f"{ampel(i['niveau'])} {'' if i['niveau'] is None else zahl(i['niveau'], 2)}",
                "Richtung": f"{pfeil(i['richtung'])} {'' if i['richtung'] is None else zahl(i['richtung'], 2)}",
                "Gewicht": i["gewicht"],
                "Hinweis": i.get("grund") or "",
            })
        st.dataframe(pd.DataFrame(zeilen), hide_index=True, width="stretch")
        st.caption("Niveau/Richtung in Standardabweichungen, Vorzeichen so gedreht, dass + = gut für den Sektor. "
                   "🟢 > +0,5 · 🟡 dazwischen · 🔴 < –0,5 · ↑ verbessert sich · ↓ verschlechtert sich.")
        st.markdown("**Bewertung:** " + " · ".join(s["bewertung"]) +
                    f" → {'+' if s['bonus'] >= 0 else '–'}{zahl(abs(s['bonus']), 3)}")
        if s.get("kgv_historie"):
            hist = {int(j): v for j, v in s["kgv_historie"].items()}
            jahre = sorted(hist)
            fig = go.Figure(go.Bar(x=[str(j) for j in jahre] + ["aktuell"],
                                   y=[hist[j] for j in jahre] + [s["kgv"] or 0]))
            fig.update_layout(height=220, margin=dict(l=10, r=10, t=30, b=10), title="Sektor-KGV (Damodaran, Median der Branchen)")
            st.plotly_chart(fig, width="stretch")

st.caption("Quellen: FRED (Federal Reserve Bank of St. Louis), Yahoo Finance (Sektor-ETFs), "
           "Prof. A. Damodaran, NYU Stern (Branchen-KGV und -Beta). Regeln und Gewichte: config/makro.yaml.")
