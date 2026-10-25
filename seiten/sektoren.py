from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from kern.format import prozent, zahl
from seiten import gemeinsam as g
from makro_sektoren import aktualisieren, gespeichert, lade_makro_cfg

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
if not cfg.get("aktiv", True):
    st.info("Der Multiplikator ist in config/makro.yaml ausgeschaltet – die Faktoren werden nur angezeigt.")
for h in daten.get("hinweise", []):
    st.warning(h)

sektoren = daten["sektoren"]

# ------------------------------------------------------------ Zyklusuhr
st.subheader("Zyklusuhr")
fig = go.Figure()
grenze = 2.5
for (x0, x1, y0, y1, phase) in ((0, grenze, -grenze, 0, "erholung"), (0, grenze, 0, grenze, "aufschwung"),
                                (-grenze, 0, 0, grenze, "boom"), (-grenze, 0, -grenze, 0, "abschwung")):
    fig.add_shape(type="rect", x0=x0, x1=x1, y0=y0, y1=y1, fillcolor=phasen[phase]["farbe"], opacity=0.12,
                  line_width=0, layer="below")
    fig.add_annotation(x=(x0 + x1) / 2, y=y1 * 0.92 if y1 > 0 else y0 * 0.92,
                       text=f"<b>{phasen[phase]['name']}</b> · Faktor {zahl(phasen[phase]['faktor'], 2)}",
                       showarrow=False, font=dict(color=phasen[phase]["farbe"], size=12))
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
fig.update_layout(height=520, showlegend=False, margin=dict(l=10, r=10, t=10, b=10),
                  xaxis=dict(range=[-grenze, grenze], title="Richtung: verschlechtert sich ← → verbessert sich",
                             zeroline=True, zerolinewidth=2),
                  yaxis=dict(range=[-grenze, grenze], title="Niveau: schlechter ↓ ↑ besser als üblich",
                             zeroline=True, zerolinewidth=2))
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
