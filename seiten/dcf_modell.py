"""Eigenes DCF-Modell: ① Annahmen → ② Free-Cashflow-Rechnung → ③ Abzinsung (Zins, Diskontfaktor, Barwert)."""
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import auswertung
from kern import dcf_modell as m
from kern.format import betrag, prozent, zahl
from kern.konfig import KonfigFehler
from seiten import gemeinsam as g
from speicher import db

st.title("📐 DCF-Modell")
st.caption("Dein eigenes Bewertungsmodell: Annahmen festlegen, daraus den Free Cashflow je Jahr rechnen und "
           "mit dem Zinssatz auf heute abzinsen. Alle Felder sind mit Werten aus den Abschlüssen vorbelegt.")
con = g.verbindung()
titel_liste = db.titel_alle(con)
if not titel_liste:
    st.info("Noch keine Titel vorhanden.")
    st.page_link(g.SEITE_IMPORT, label="Zum Import", icon="➕")
    st.stop()

ticker = g.titel_wahl(titel_liste, "dcf_titel")
t = db.titel(con, ticker)
analysen = db.analysen_fuer(con, ticker)
if not analysen:
    st.info("Für diesen Titel gibt es noch keine Analyse.")
    st.stop()
analyse = analysen[-1]
basis = auswertung.modell_basis(analyse)
if basis is None:
    st.warning("Die letzte Analyse stammt aus der Zeit vor dem DCF-Modell. Bitte einmal neu analysieren.")
    if st.button("🔄 Jetzt neu analysieren", type="primary") and g.neu_analysieren(ticker):
        st.rerun()
    st.stop()
if basis.grund:
    st.warning(f"Kein DCF-Modell möglich: {basis.grund}")
    st.stop()

try:
    dcf_cfg = auswertung.dcf_konfig(con)
except KonfigFehler as ex:
    st.error(f"Fehler in config/dcf.yaml: {ex}")
    st.stop()
vorgaben = auswertung.modell_vorgaben(con, t, dcf_cfg)
dcf_roh = json.loads(analyse["dcf"]) if analyse.get("dcf") else {}
rf = dcf_roh.get("zins") or float(dcf_cfg["risikofreier_zins"]["ersatzwert"])
# Startwachstum: geglättetes Umsatzwachstum der letzten 5 Jahre (Kennzahl B), begrenzt wie im automatischen DCF
optionen = g.schwellen()["optionen"]
umsatz_kz = next((z["rohwert"] for z in db.kennzahlen_fuer(con, [analyse["id"]]) if z["schluessel"] == "umsatz_cagr"), None)
if umsatz_kz is None:
    umsatz_kz = m.kennzahlen_historie(basis)["umsatz_cagr"]
wachstum_auto = min(max(umsatz_kz if umsatz_kz is not None else 3.0, float(optionen["wachstum_min"])),
                    float(optionen["wachstum_max"]))
vorschlag = m.vorschlag(basis, wachstum_auto, rf, vorgaben["beta"], vorgaben["erp"], vorgaben["g_ewig"],
                        vorgaben["exit_multiple"], int(dcf_cfg.get("prognosejahre", 10)),
                        int(dcf_cfg.get("wachstumsphase", 5)))
gespeichert = db.dcf_modell(con, ticker)
w = basis.waehrung
faktor, einheit = (1e9, "Mrd.") if abs(basis.umsatz) >= 1e9 else (1e6, "Mio.")

# ------------------------------------------------------------ Zustand der Eingabefelder
# Die Werte liegen je Titel in einem eigenen Speicher (Streamlit vergisst den Inhalt von Feldern, die
# gerade nicht angezeigt werden – z. B. nach einem Titelwechsel). Die Felder werden daraus befüllt.
ss = st.session_state
P = f"dm_{ticker}_"


def k(name: str) -> str:
    return P + name


def neue_tabelle(tabelle: dict) -> None:
    ss[k("tabelle")] = tabelle
    ss.pop(k("tabelle_aktuell"), None)
    ss[k("version")] = ss.get(k("version"), 0) + 1          # neue Tabelle → Editor neu aufbauen


def setzen(a: m.Annahmen) -> None:
    """Alle Eingabefelder auf die Annahmen ``a`` setzen."""
    werte = {f: getattr(a, f) for f in ("steuersatz", "abschr_quote", "capex_quote", "nwc_quote", "rf", "beta",
                                         "erp", "fk_zins", "fk_anteil", "g_ewig", "exit_multiple",
                                         "endwert_methode", "mitte_jahr")}
    werte.update(
        wacc_eigen=a.wacc_manuell is not None,
        wacc_manuell=round(a.wacc_manuell if a.wacc_manuell is not None else a.wacc, 2),
        umsatz_eigen=a.umsatz_start is not None,
        umsatz_start=round((a.umsatz_start if a.umsatz_start is not None else basis.umsatz) / faktor, 3),
        ns_eigen=a.nettoschulden is not None,
        nettoschulden=round((a.nettoschulden if a.nettoschulden is not None
                             else basis.schulden - basis.cash) / faktor, 3),
        fuell_jahre=a.jahre, fuell_g1=a.wachstum[0], fuell_g2=a.wachstum[-1],
        fuell_m1=a.ebit_marge[0], fuell_m2=a.ebit_marge[-1])
    ss[k("werte")] = werte
    neue_tabelle({"wachstum": list(a.wachstum), "ebit_marge": list(a.ebit_marge)})
    for schluessel in [x for x in ss if str(x).startswith("w_" + P)]:
        del ss[schluessel]


if k("werte") not in ss:
    setzen(m.Annahmen.aus_dict(gespeichert["annahmen"]) if gespeichert else vorschlag)
werte = ss[k("werte")]


def eingabe(ort, art: str, name: str, beschriftung: str, **kw):
    """Eingabefeld ``art`` (z. B. "number_input") für den Wert ``name``; merkt sich die Eingabe."""
    wk = "w_" + P + name
    if wk not in ss:
        ss[wk] = werte[name]
    werte[name] = getattr(ort, art)(beschriftung, key=wk, **kw)
    return werte[name]

# ------------------------------------------------------------ Kopf
if gespeichert:
    st.success(f"Gespeichertes Modell vom {gespeichert['zeitpunkt'][:16].replace('T', ' ')}"
               + (f" – „{gespeichert['notiz']}“" if gespeichert.get("notiz") else "")
               + (" · **zählt im Score**" if gespeichert["im_score"] else " · zählt nicht im Score"))
k1, k2 = st.columns(2)
if k1.button("↺ Alle Felder auf den Vorschlag zurücksetzen", width="stretch"):
    setzen(vorschlag)
    st.rerun()
if gespeichert and k2.button("↺ Gespeichertes Modell neu laden", width="stretch"):
    setzen(m.Annahmen.aus_dict(gespeichert["annahmen"]))
    st.rerun()
st.caption(f"Datenbasis: Analyse vom {analyse['zeitpunkt'][:10]}, Datenstand {basis.datenstand}. "
           f"Beträge in {einheit} {w}.")

# ============================================================ ① Annahmen
st.header("① Annahmen")
hist = m.kennzahlen_historie(basis)
with st.expander("Vergangenheit zum Vergleich (Geschäftsjahre)", expanded=True):
    def quote(x, u):
        return zahl(x / u * 100) if x is not None and u else "–"

    zeilen_h, vorher = [], None
    for j in basis.historie:
        u = j.get("umsatz")
        zeilen_h.append({
            "Jahr": str(j["jahr"]), f"Umsatz ({einheit})": "–" if u is None else zahl(u / faktor, 2),
            "Wachstum": "–" if not (u and vorher) else prozent((u / vorher - 1) * 100),
            "EBIT-Marge %": quote(j.get("ebit"), u), "Abschreibungen % Umsatz": quote(j.get("abschreibungen"), u),
            "Capex % Umsatz": quote(j.get("capex"), u)})
        vorher = u
    zeilen_h.append({"Jahr": "12 Monate", f"Umsatz ({einheit})": zahl(basis.umsatz / faktor, 2), "Wachstum": "–",
                     "EBIT-Marge %": quote(basis.ebit, basis.umsatz),
                     "Abschreibungen % Umsatz": quote(basis.abschreibungen, basis.umsatz),
                     "Capex % Umsatz": quote(basis.capex, basis.umsatz)})
    st.dataframe(pd.DataFrame(zeilen_h), hide_index=True, width="stretch")
    st.caption(f"Umsatzwachstum pro Jahr (CAGR, {hist['jahre_cagr']} Jahre): {prozent(hist['umsatz_cagr'])} · "
               f"geglättet (Kennzahl B): {prozent(umsatz_kz)} → Vorschlag für Jahr 1–5: {prozent(wachstum_auto)} · "
               f"Working Capital heute: {prozent(hist['nwc_quote'])} vom Umsatz.")

st.subheader("Umsatz und Marge je Jahr")
c1, c2 = st.columns(2)
umsatz_eigen = eingabe(c1, "toggle", "umsatz_eigen", "Startumsatz selbst festlegen",
                       help="Z. B. ein „normaler“ Umsatz, wenn die letzten 12 Monate durch Sondereffekte verzerrt sind.")
if umsatz_eigen:
    eingabe(c1, "number_input", "umsatz_start", f"Startumsatz ({einheit} {w})", min_value=0.0, step=0.1, format="%.3f")
else:
    c1.caption(f"Startumsatz = letzte 12 Monate: {betrag(basis.umsatz, w)}")
mitte = eingabe(c2, "toggle", "mitte_jahr", "Cashflows zur Jahresmitte abzinsen",
                help="Das Geld fließt übers Jahr verteilt, nicht erst am 31.12. Dann wird mit t – 0,5 abgezinst "
                     "(etwas höherer Wert). Analysten nennen das „Mid-Year Convention“.")

with st.popover("⚡ Tabelle schnell ausfüllen", width="stretch"):
    st.write("Füllt die Tabelle mit einem gleichmäßigen Übergang vom ersten zum letzten Jahr.")
    eingabe(st, "number_input", "fuell_jahre", "Prognosejahre", min_value=3, max_value=15, step=1)
    f1, f2 = st.columns(2)
    eingabe(f1, "number_input", "fuell_g1", "Wachstum Jahr 1 (%)", step=0.5, format="%.2f")
    eingabe(f2, "number_input", "fuell_g2", "Wachstum letztes Jahr (%)", step=0.5, format="%.2f")
    eingabe(f1, "number_input", "fuell_m1", "EBIT-Marge Jahr 1 (%)", step=0.5, format="%.2f")
    eingabe(f2, "number_input", "fuell_m2", "EBIT-Marge letztes Jahr (%)", step=0.5, format="%.2f")
    if st.button("Tabelle damit füllen", type="primary"):
        n = int(werte["fuell_jahre"])
        neue_tabelle({"wachstum": m.linear(werte["fuell_g1"], werte["fuell_g2"], n),
                      "ebit_marge": m.linear(werte["fuell_m1"], werte["fuell_m2"], n)})
        st.rerun()

editor_key = k(f"editor_{ss[k('version')]}")
if editor_key not in ss and k("tabelle_aktuell") in ss:      # Änderungen nach einem Titelwechsel wiederherstellen
    ss[k("tabelle")] = ss.pop(k("tabelle_aktuell"))
tabelle = ss[k("tabelle")]
jahr0 = basis.historie[-1]["jahr"] if basis.historie else pd.Timestamp(basis.datenstand or "today").year
df_ein = pd.DataFrame({"Jahr": [f"{i} ({jahr0 + i})" for i in range(1, len(tabelle["wachstum"]) + 1)],
                       "Umsatzwachstum %": tabelle["wachstum"], "EBIT-Marge %": tabelle["ebit_marge"]})
bearbeitet = st.data_editor(
    df_ein, hide_index=True, width="stretch", disabled=["Jahr"], num_rows="fixed",
    key=editor_key,
    column_config={"Umsatzwachstum %": st.column_config.NumberColumn(format="%.2f", step=0.1, required=True),
                   "EBIT-Marge %": st.column_config.NumberColumn(format="%.2f", step=0.1, required=True)})
ss[k("tabelle_aktuell")] = {"wachstum": [float(x) for x in bearbeitet["Umsatzwachstum %"].fillna(0.0)],
                            "ebit_marge": [float(x) for x in bearbeitet["EBIT-Marge %"].fillna(0.0)]}
st.caption("Zahl antippen zum Ändern. Mehr oder weniger Jahre: über „Tabelle schnell ausfüllen“.")

st.subheader("Steuern und Reinvestitionen (in % vom Umsatz)")
r1, r2, r3, r4 = st.columns(4)
eingabe(r1, "number_input", "steuersatz", "Steuersatz %", min_value=0.0, max_value=60.0, step=0.5, format="%.1f",
        help="Effektiver Steuersatz des letzten Geschäftsjahres (begrenzt auf 0–35 %).")
eingabe(r2, "number_input", "abschr_quote", "Abschreibungen %", min_value=0.0, step=0.1, format="%.2f",
        help=f"Ø letzte 3 Jahre: {prozent(hist['abschr_quote_3j'])}")
eingabe(r3, "number_input", "capex_quote", "Investitionen (Capex) %", min_value=0.0, step=0.1, format="%.2f",
        help=f"Ø letzte 3 Jahre: {prozent(hist['capex_quote_3j'])}. Langfristig liegt Capex meist etwas "
             "über den Abschreibungen, sonst schrumpft die Firma.")
eingabe(r4, "number_input", "nwc_quote", "Working Capital %", step=0.5, format="%.2f",
        help="Vorräte + Forderungen – Lieferantenschulden, in % vom Umsatz. Wächst der Umsatz, wird Geld "
             f"gebunden (positive Quote) bzw. frei (negative Quote). Heute: {prozent(hist['nwc_quote'])}")

st.subheader("Zinssatz (WACC)")
z1, z2, z3 = st.columns(3)
eingabe(z1, "number_input", "rf", "Risikofreier Zins %", step=0.05, format="%.2f",
        help=f"10-jährige US-Staatsanleihe, {dcf_roh.get('zins_quelle', '')} {dcf_roh.get('zins_datum', '')}")
eingabe(z2, "number_input", "beta", "Beta", min_value=0.0, step=0.05, format="%.2f",
        help=f"Schwankung gegenüber dem Gesamtmarkt (1 = wie der Markt). Quelle: {vorgaben['beta_quelle']}")
eingabe(z3, "number_input", "erp", "Marktrisikoprämie %", step=0.25, format="%.2f",
        help="Mehrrendite, die man für Aktien statt Anleihen verlangt.")
z4, z5, z6 = st.columns(3)
eingabe(z4, "number_input", "fk_zins", "Zins auf Schulden % (vor Steuern)", min_value=0.0, step=0.25, format="%.2f",
        help=f"Vorschlag: Zinsaufwand ÷ Finanzschulden = {prozent(basis.zinsaufwand / basis.schulden * 100) if basis.schulden and basis.zinsaufwand else '–'}")
eingabe(z5, "number_input", "fk_anteil", "Anteil Schulden am Kapital %", min_value=0.0, max_value=95.0, step=1.0,
        format="%.1f", help="Finanzschulden ÷ (Finanzschulden + Börsenwert).")
wacc_eigen = eingabe(z6, "toggle", "wacc_eigen", "WACC direkt eingeben")
if wacc_eigen:
    eingabe(z6, "number_input", "wacc_manuell", "WACC %", min_value=0.5, step=0.25, format="%.2f")

st.subheader("Endwert nach dem letzten Prognosejahr")
e1, e2, e3 = st.columns(3)
eingabe(e1, "number_input", "g_ewig", "Ewiges Wachstum %", step=0.25, format="%.2f",
        help="So wächst der Free Cashflow nach dem letzten Prognosejahr für immer. Üblich: 2–3 %.")
eingabe(e2, "number_input", "exit_multiple", "Exit-Multiple (Unternehmenswert ÷ EBITDA)", min_value=1.0, step=0.5,
        format="%.1f", help=f"Wofür die Firma am Ende verkauft würde. Vorschlag: {vorgaben['multiple_quelle']}")
eingabe(e3, "selectbox", "endwert_methode", "Methode", options=list(m.METHODEN), format_func=m.METHODEN.get)

st.subheader("Von Unternehmenswert zu Aktienwert")
n1, n2 = st.columns(2)
ns_eigen = eingabe(n1, "toggle", "ns_eigen", "Nettoschulden selbst festlegen")
if ns_eigen:
    eingabe(n1, "number_input", "nettoschulden", f"Nettoschulden ({einheit} {w}, negativ = Nettocash)",
            step=0.1, format="%.3f")
n2.caption(f"Aus der Bilanz: Finanzschulden {betrag(basis.schulden, w)} – Cash und kurzfristige Wertpapiere "
           f"{betrag(basis.cash, w)} = Nettoschulden {betrag(basis.schulden - basis.cash, w)}."
           + (f" Nicht enthalten: langfristige Wertpapiere {betrag(basis.langfr_wertpapiere, w)} – bei Bedarf "
              "selbst abziehen." if basis.langfr_wertpapiere else "")
           + f" Aktien: {zahl(basis.aktien / 1e6, 1)} Mio.")

annahmen = m.Annahmen(
    **ss[k("tabelle_aktuell")],
    steuersatz=werte["steuersatz"], abschr_quote=werte["abschr_quote"], capex_quote=werte["capex_quote"],
    nwc_quote=werte["nwc_quote"], rf=werte["rf"], beta=werte["beta"], erp=werte["erp"], fk_zins=werte["fk_zins"],
    fk_anteil=werte["fk_anteil"], wacc_manuell=werte["wacc_manuell"] if wacc_eigen else None,
    g_ewig=werte["g_ewig"], exit_multiple=werte["exit_multiple"], endwert_methode=werte["endwert_methode"],
    mitte_jahr=mitte, umsatz_start=werte["umsatz_start"] * faktor if umsatz_eigen else None,
    nettoschulden=werte["nettoschulden"] * faktor if ns_eigen else None)
erg = m.rechnen(annahmen, basis)

if not wacc_eigen:
    st.caption(f"Eigenkapitalkosten = {prozent(annahmen.rf, 2)} + {zahl(annahmen.beta, 2)} × "
               f"{prozent(annahmen.erp, 2)} = **{prozent(annahmen.ek_kosten, 2)}** · "
               f"WACC = {prozent(100 - annahmen.fk_anteil)} × {prozent(annahmen.ek_kosten, 2)} + "
               f"{prozent(annahmen.fk_anteil)} × {prozent(annahmen.fk_zins, 2)} × (1 – {prozent(annahmen.steuersatz)}) "
               f"= **{prozent(annahmen.wacc, 2)}**")
if erg.grund:
    st.error(f"Keine Bewertung möglich: {erg.grund}")
    st.stop()


# ============================================================ ② Free-Cashflow-Rechnung
def mb(v):
    return zahl(v / faktor, 2)


st.header("② Free-Cashflow-Rechnung")
st.caption(f"In {einheit} {w}. Free Cashflow an alle Kapitalgeber (vor Zinsen) – deshalb wird später mit dem WACC "
           "abgezinst und erst am Ende die Nettoschulden abgezogen.")
spalten = {"Basis (12 M.)": {
    "Umsatz": mb(annahmen.umsatz_start or basis.umsatz), "Wachstum": "",
    "EBIT": mb(basis.ebit) if basis.ebit is not None and annahmen.umsatz_start is None else "",
    "EBIT-Marge": prozent(hist["ebit_marge_ttm"]) if annahmen.umsatz_start is None else "",
    "– Steuern": "", "= NOPAT (Gewinn nach Steuern)": "",
    "+ Abschreibungen": mb(basis.abschreibungen) if basis.abschreibungen is not None else "",
    "– Investitionen (Capex)": mb(-basis.capex) if basis.capex is not None else "",
    "– Zunahme Working Capital": "", "= Free Cashflow": ""}}
for z in erg.zeilen:
    spalten[f"{z['jahr']} ({jahr0 + z['jahr']})"] = {
        "Umsatz": mb(z["umsatz"]), "Wachstum": prozent(z["wachstum"]), "EBIT": mb(z["ebit"]),
        "EBIT-Marge": prozent(z["ebit_marge"]), "– Steuern": mb(-z["steuern"]),
        "= NOPAT (Gewinn nach Steuern)": mb(z["nopat"]), "+ Abschreibungen": mb(z["abschreibungen"]),
        "– Investitionen (Capex)": mb(-z["capex"]), "– Zunahme Working Capital": mb(-z["delta_nwc"]),
        "= Free Cashflow": mb(z["fcf"])}
st.dataframe(pd.DataFrame(spalten), width="stretch")

# ============================================================ ③ Abzinsung
st.header("③ Abzinsung")
st.caption("Barwert = Free Cashflow × Diskontfaktor. Der Diskontfaktor 1 ÷ (1 + Zins)^t sagt, was ein Euro im Jahr t "
           "heute wert ist. Die letzte Zeile ist der Endwert (Wert aller Jahre danach), abgezinst ab dem letzten "
           "Prognosejahr.")
abz = [{"Jahr": f"{z['jahr']} ({jahr0 + z['jahr']})", f"Free Cashflow ({einheit})": mb(z["fcf"]),
        "Zinssatz": prozent(z["zinssatz"], 2), "t": zahl(z["zeit"], 1),
        "Diskontfaktor": zahl(z["diskontfaktor"], 4), f"Barwert ({einheit})": mb(z["barwert"])} for z in erg.zeilen]
abz.append({"Jahr": "Endwert", f"Free Cashflow ({einheit})": mb(erg.endwert),
            "Zinssatz": prozent(erg.wacc, 2), "t": zahl(erg.endwert_zeit, 1),
            "Diskontfaktor": zahl(erg.endwert_diskontfaktor, 4), f"Barwert ({einheit})": mb(erg.endwert_barwert)})
st.dataframe(pd.DataFrame(abz), hide_index=True, width="stretch", height=35 * (len(abz) + 1) + 3)

with st.expander("So entsteht der Endwert", expanded=False):
    st.markdown(
        f"- **Ewiges Wachstum (Gordon):** FCF im letzten Jahr {mb(erg.fcf_letztes)} × (1 + {prozent(annahmen.g_ewig, 2)})"
        f" ÷ ({prozent(erg.wacc, 2)} – {prozent(annahmen.g_ewig, 2)}) = **{mb(erg.endwert_gordon) if erg.endwert_gordon is not None else 'nicht berechenbar'}**"
        + (f" – entspricht {zahl(erg.impl_multiple, 1)}× EBITDA" if erg.impl_multiple is not None else "") + "\n"
        f"- **Exit-Multiple:** EBITDA im letzten Jahr {mb(erg.ebitda_letztes)} × {zahl(annahmen.exit_multiple, 1)}"
        f" = **{mb(erg.endwert_multiple) if erg.endwert_multiple is not None else 'nicht berechenbar'}**"
        + (f" – entspricht {prozent(erg.impl_wachstum, 2)} ewigem Wachstum" if erg.impl_wachstum is not None else "")
        + f"\n- **Verwendet:** {erg.endwert_text} = {mb(erg.endwert)} {einheit} {w}")
    st.caption("Passen die beiden Werte grob zusammen, sind die Annahmen in sich stimmig. Weichen sie stark ab, "
               "ist entweder das Multiple oder das ewige Wachstum unrealistisch.")

bruecke = pd.DataFrame([
    ("Summe Barwerte der Free Cashflows", mb(erg.summe_barwerte)),
    ("+ Barwert Endwert", mb(erg.endwert_barwert)),
    ("= Unternehmenswert", mb(erg.unternehmenswert)),
    ("– Nettoschulden" + (" ✏️" if annahmen.nettoschulden is not None else ""), mb(-erg.nettoschulden)),
    ("= Eigenkapitalwert", mb(erg.eigenkapitalwert)),
    ("÷ Aktien (Mio.)", zahl(basis.aktien / 1e6, 1)),
    (f"= fairer Wert je Aktie ({w})", zahl(erg.fairer_wert, 2)),
], columns=["", f"{einheit} {w}"])
b1, b2 = st.columns([3, 2])
b1.dataframe(bruecke, hide_index=True, width="stretch")
with b2:
    st.metric(f"Fairer Wert je Aktie ({w})", zahl(erg.fairer_wert, 2))
    st.metric(f"Kurs ({w})", zahl(basis.kurs, 2))
    st.metric("Sicherheitsmarge", prozent(erg.sicherheitsmarge),
              help="(fairer Wert – Kurs) ÷ fairer Wert. Positiv = Kurs liegt unter dem fairen Wert.")
    st.caption(f"Anteil Endwert am Unternehmenswert: {prozent(erg.endwert_anteil, 0)}")
for h in erg.hinweise:
    st.warning(h)

fig = go.Figure()
x = [f"{z['jahr']} ({jahr0 + z['jahr']})" for z in erg.zeilen]
fig.add_bar(x=x, y=[z["fcf"] / faktor for z in erg.zeilen], name="Free Cashflow", marker_color="#95a5a6")
fig.add_bar(x=x, y=[z["barwert"] / faktor for z in erg.zeilen], name="Barwert heute", marker_color="#2c7fb8")
fig.update_layout(barmode="group", height=300, xaxis=dict(type="category"), margin=dict(l=10, r=10, t=40, b=20),
                  title=f"Free Cashflow und Barwert je Jahr ({einheit} {w})", legend=dict(orientation="h", y=-0.15))
st.plotly_chart(fig, width="stretch")


def heatmap(emp: dict, spalten_text) -> None:
    abstand = [[None if v is None else (v - basis.kurs) / basis.kurs * 100 for v in zeile] for zeile in emp["werte"]]
    fig = go.Figure(go.Heatmap(
        z=abstand, x=[spalten_text(x) for x in emp["spalten"]], y=[f"WACC {prozent(r, 2)}" for r in emp["zeilen"]],
        text=[[zahl(v, 2) for v in zeile] for zeile in emp["werte"]], texttemplate="%{text}",
        colorscale="RdYlGn", zmid=0, showscale=False, hovertemplate="%{y}, %{x}: fairer Wert %{text}<extra></extra>"))
    fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, width="stretch")


st.subheader("Empfindlichkeit: fairer Wert je Aktie")
st.caption(f"Grün = über dem Kurs von {zahl(basis.kurs, 2)} {w}, rot = darunter. Die Mitte sind deine Annahmen.")
h1, h2 = st.columns(2)
with h1:
    st.markdown("**Zinssatz × ewiges Wachstum**")
    heatmap(m.empfindlichkeit(annahmen, basis, "wachstum"), lambda x: f"g {prozent(x, 2)}")
with h2:
    st.markdown("**Zinssatz × Exit-Multiple**")
    heatmap(m.empfindlichkeit(annahmen, basis, "multiple"), lambda x: f"{zahl(x, 1)}× EBITDA")
if annahmen.endwert_methode != "durchschnitt":
    st.caption(f"Hinweis: Mit der Methode „{m.METHODEN[annahmen.endwert_methode]}“ ändert nur eine der beiden "
               "Tabellen den Wert.")

# ============================================================ Speichern
st.header("💾 Speichern und für den Score verwenden")
dcf_erg, _ = auswertung.dcf_berechnen(analyse, t, db.dcf_manuell(con, ticker), g.schwellen(), dcf_cfg)
if dcf_erg is not None and dcf_erg.grund is None:
    st.caption(f"Zum Vergleich – automatisches DCF (Bear/Base/Bull): fairer Wert {zahl(dcf_erg.fairer_wert, 2)} {w}, "
               f"Sicherheitsmarge {prozent(dcf_erg.sicherheitsmarge)}.")
geaendert = gespeichert is None or gespeichert["annahmen"] != annahmen.als_dict()
if gespeichert and geaendert:
    st.info("Du hast Änderungen gegenüber dem gespeicherten Modell, die noch nicht gespeichert sind.")
with st.form(k("speichern")):
    notiz = st.text_input("Notiz (optional)", value=(gespeichert or {}).get("notiz", "") or "",
                          placeholder="z. B. Marge normalisiert wegen Sondereffekt 2024")
    im_score = st.checkbox("Für den Score verwenden", value=bool(gespeichert and gespeichert["im_score"]),
                           help="Ersetzt die automatische DCF-Sicherheitsmarge (Kategorie A) durch die Sicherheitsmarge "
                                "aus diesem Modell. Bei jeder neuen Analyse rechnet das Modell mit deinen Annahmen "
                                "und den neuen Zahlen (Umsatz, Kurs, Schulden) weiter.")
    if st.form_submit_button("Modell speichern", type="primary"):
        db.dcf_modell_speichern(con, ticker, annahmen.als_dict(), im_score, notiz)
        st.toast("Modell gespeichert.")
        st.rerun()
if gespeichert:
    with st.popover("🗑️ Gespeichertes Modell verwerfen"):
        st.write("Danach zählt wieder das automatische DCF im Score. Frühere Stände bleiben in der Datenbank.")
        if st.button("Ja, verwerfen", type="primary"):
            db.dcf_modell_speichern(con, ticker, None, False, "verworfen")
            st.rerun()
