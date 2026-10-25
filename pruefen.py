"""Prüfprogramm: zeigt alle Rohwerte für einen oder mehrere Ticker an.

Aufruf:  pruefen.bat AAPL KO CAT
Speichert nichts in der Datenbank. Schreibt zusätzlich eine Datei
pruefung_<TICKER>.txt, die du mit den Geschäftsberichten vergleichen kannst.
"""
import sys

from analyse import AnalyseFehler, kennzahlen_berechnen
from kern.format import betrag
from kern.kennzahlen import stichtag
from kern.konfig import lade_schwellen, sektor_fuer_sic
from kern.punkte import punkte_fuer

GRUNDWERTE = ["umsatz", "bruttogewinn", "ebit", "nettogewinn", "ocf", "capex", "abschreibungen", "zinsaufwand",
              "dividenden", "rueckkaeufe", "aktienausgabe"]


def bericht(ticker: str) -> str:
    r = kennzahlen_berechnen(ticker)
    s = lade_schwellen()
    fd = r.fd
    z = [f"{'=' * 78}", f"{r.name} ({r.ticker}) – CIK {r.cik}, SIC {r.sic} {r.sic_beschreibung}",
         f"Sektor: {sektor_fuer_sic(r.sic)} · Berichtswährung: {fd.waehrung} · Kurswährung: {fd.kurs_waehrung}",
         f"{'=' * 78}"]
    for h in r.hinweise:
        z.append(f"HINWEIS: {h}")
    z.append("")
    z.append("Grundwerte der letzten 12 Monate:")
    for k in GRUNDWERTE:
        w = fd.ttm.get(k)
        z.append(f"  {k:<16} {betrag(w.wert, fd.waehrung) if w else '– nicht gefunden':>22}   "
                 f"{('bis ' + w.ende.isoformat() + '  ' + w.quelle) if w else ''}")
    tag = stichtag(fd)
    z.append(f"\nBilanz zum {tag}:")
    for k, liste in fd.bilanz.items():
        w = next((x for x in liste if tag and abs((x.ende - tag).days) <= 5), None)
        if w:
            anzeige = f"{w.wert:,.0f} Stück" if k.startswith("aktien") else betrag(w.wert, fd.waehrung)
            z.append(f"  {k:<28} {anzeige:>20}   {w.quelle}")
    if fd.aktien_aktuell:
        z.append(f"\nAktien: {fd.aktien_aktuell.wert:,.0f} ({fd.aktien_aktuell.quelle})")
    if fd.kurs_aktuell:
        z.append(f"Kurs:   {fd.kurs_aktuell.wert:.2f} {fd.kurs_waehrung} ({fd.kurs_aktuell.quelle})")
    z.append("\nUmsatz je Geschäftsjahr: " + ", ".join(
        f"{w.ende:%Y}: {betrag(w.wert, fd.waehrung)}" for w in fd.jahre.get("umsatz", [])[-11:]))
    z.append("\nKennzahlen:")
    for e in r.ergebnisse:
        kz = s["kennzahlen"][e.schluessel]
        p = None if (e.grund and e.fixpunkte is None) else punkte_fuer(e.schluessel, e.rohwert, e.fixpunkte, s)
        roh = "–" if e.rohwert is None else f"{e.rohwert:.2f} {kz['einheit']}"
        z.append(f"\n  [{kz['kategorie']}] {kz['name']}: {roh}  →  {('%.1f' % p) if p is not None else 'ausgelassen'} Punkte")
        if e.grund:
            z.append(f"      Grund: {e.grund}")
        if e.details:
            z.append(f"      Rechenweg: {e.details}")
        if e.hinweis:
            z.append(f"      Hinweis: {e.hinweis}")
        if e.datenstand:
            z.append(f"      Datenstand: {e.datenstand}")
        if e.quelle:
            z.append(f"      Quelle: {e.quelle}")
    return "\n".join(z)


if __name__ == "__main__":
    tickers = sys.argv[1:] or ["AAPL", "KO", "CAT"]
    for t in tickers:
        try:
            text = bericht(t)
        except AnalyseFehler as ex:
            text = f"{t}: FEHLER – {ex}"
        print(text + "\n")
        with open(f"pruefung_{t.upper()}.txt", "w", encoding="utf-8") as f:
            f.write(text)
