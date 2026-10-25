"""Berechnung der 14 Kennzahlen der Kategorien A–D.

Dieses Modul kennt weder die SEC noch die Oberfläche. Es bekommt fertig
aufbereitete Werte (``Finanzdaten``) und liefert pro Kennzahl ein
``Ergebnis`` mit Rohwert, Quelle, Datenstand und ggf. dem Grund, warum
die Kennzahl ausgelassen wurde. Dadurch ist alles einzeln testbar.

Begriffe ("Konzepte") für die Eingangswerte:
  Zeitraumwerte (ttm = letzte 12 Monate, jahre = Geschäftsjahre):
    umsatz, bruttogewinn, herstellkosten, ebit, nettogewinn, ocf, capex,
    abschreibungen, zinsaufwand, steuern, vorsteuergewinn, dividenden,
    rueckkaeufe, aktienausgabe, aktien_verwaessert
  Stichtagswerte (bilanz):
    bilanzsumme, umlaufvermoegen, kurzfr_verbindlichkeiten, verbindlichkeiten,
    eigenkapital, gewinnruecklagen, cash, kurzfr_wertpapiere,
    ltd_gesamt, ltd_langfristig, ltd_kurzfristig, schulden_kurzfristig_gesamt,
    kurzfr_kredite, commercial_paper
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from kern.format import betrag, prozent, zahl


@dataclass
class Wert:
    wert: float
    ende: date
    quelle: str
    start: date | None = None


@dataclass
class Finanzdaten:
    waehrung: str = "USD"
    ttm: dict[str, Wert] = field(default_factory=dict)
    ttm_ist_geschaeftsjahr: bool = False          # True, wenn keine Quartalsdaten (z. B. 20-F)
    jahre: dict[str, list[Wert]] = field(default_factory=dict)
    bilanz: dict[str, list[Wert]] = field(default_factory=dict)
    aktien_aktuell: Wert | None = None
    kurs_aktuell: Wert | None = None
    kurse: pd.Series | None = None                # Schlusskurse (um Splits bereinigt), Index = Datum
    kurs_waehrung: str | None = None
    kurs_quelle: str = ""


@dataclass
class Ergebnis:
    schluessel: str
    rohwert: float | None = None
    fixpunkte: float | None = None
    quelle: str = ""
    datenstand: str = ""
    grund: str | None = None        # gesetzt, wenn die Kennzahl ausgelassen wird
    details: str = ""               # Rechenweg zum Nachprüfen
    hinweis: str = ""               # Zusatzinfo, z. B. "hochgerechnet"


# ---------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------

def _iso(d: date | None) -> str:
    return d.isoformat() if d else ""


def _nahe(a: date, b: date, tage: int) -> bool:
    return abs((a - b).days) <= tage


def wert_am(liste: list[Wert] | None, datum: date, toleranz: int = 10) -> Wert | None:
    if not liste:
        return None
    treffer = [w for w in liste if _nahe(w.ende, datum, toleranz)]
    if not treffer:
        return None
    return min(treffer, key=lambda w: abs((w.ende - datum).days))


def stichtag(fd: Finanzdaten) -> date | None:
    """Letzter Bilanzstichtag (aus der Bilanzsumme, sonst aus dem Umlaufvermögen)."""
    for konzept in ("bilanzsumme", "umlaufvermoegen", "eigenkapital"):
        liste = fd.bilanz.get(konzept)
        if liste:
            return max(w.ende for w in liste)
    return None


def bilanzwert(fd: Finanzdaten, konzept: str, datum: date) -> Wert | None:
    return wert_am(fd.bilanz.get(konzept), datum, toleranz=5)


def geschaeftsjahre(fd: Finanzdaten, konzept: str = "umsatz", anzahl: int = 10) -> list[date]:
    """Enddaten der letzten ``anzahl`` Geschäftsjahre (neueste zuletzt)."""
    liste = fd.jahre.get(konzept) or []
    enden = sorted({w.ende for w in liste})
    return enden[-anzahl:]


def jahreswert(fd: Finanzdaten, konzept: str, ende: date) -> Wert | None:
    return wert_am(fd.jahre.get(konzept), ende, toleranz=10)


def _quellen(*werte: Wert | None) -> str:
    teile = []
    for w in werte:
        if w is not None and w.quelle and w.quelle not in teile:
            teile.append(w.quelle)
    return "; ".join(teile)


def finanzschulden(fd: Finanzdaten, datum: date) -> tuple[float, str]:
    """Zinstragende Finanzschulden zum Stichtag (ohne Leasingverbindlichkeiten).

    Regel, um Doppelzählungen zu vermeiden:
      langfristiger Teil  = LongTermDebtNoncurrent, sonst LongTermDebt – kurzfristiger Teil
      kurzfristiger Teil  = DebtCurrent (enthält alles Kurzfristige), sonst
                            LongTermDebtCurrent + ShortTermBorrowings/CommercialPaper
    Fehlt der kurzfristige Teil der langfristigen Schulden ganz, werden ersatzweise die
    Tilgungen der nächsten 12 Monate verwendet.

    Manche Firmen (z. B. Caterpillar) melden Schulden in Quartalsberichten nur unter
    eigenen Feldnamen. Gibt es zum Stichtag keine Angabe, wird der letzte Stand der
    vergangenen 13 Monate verwendet und in der Quelle vermerkt.
    Fehlen alle Angaben, werden 0 Finanzschulden angenommen.
    """
    stand = _schulden_stichtag(fd, datum)
    if stand is None:
        return 0.0, "keine Finanzschulden ausgewiesen"
    b = lambda k: bilanzwert(fd, k, stand)  # noqa: E731
    gesamt, lang, kurz_ltd = b("ltd_gesamt"), b("ltd_langfristig"), b("ltd_kurzfristig")
    kurz_gesamt, kredite, cp = b("schulden_kurzfristig_gesamt"), b("kurzfr_kredite"), b("commercial_paper")
    faellig = None
    if kurz_ltd is None and kurz_gesamt is None and gesamt is None and lang is not None:
        faellig = b("ltd_faellig_12m")
        kurz_ltd = faellig

    if lang is not None:
        lang_teil = lang.wert
    elif gesamt is not None:
        lang_teil = gesamt.wert - (kurz_ltd.wert if kurz_ltd else 0.0)
    else:
        lang_teil = 0.0

    if kurz_gesamt is not None:
        kurz_teil = kurz_gesamt.wert
    else:
        kurz_teil = (kurz_ltd.wert if kurz_ltd else 0.0)
        if kredite is not None:
            kurz_teil += kredite.wert
        elif cp is not None:
            kurz_teil += cp.wert

    quelle = _quellen(gesamt, lang, kurz_ltd, kurz_gesamt, kredite, cp)
    if faellig is not None:
        quelle += "; kurzfristiger Teil ersatzweise = Tilgungen der nächsten 12 Monate"
    if abs((stand - datum).days) > 5:
        quelle = f"Schulden zum {stand:%d.%m.%Y} (zum {datum:%d.%m.%Y} nicht im Standardformat gemeldet); " + quelle
    return lang_teil + kurz_teil, quelle


SCHULD_KONZEPTE = ("ltd_gesamt", "ltd_langfristig", "ltd_kurzfristig", "schulden_kurzfristig_gesamt",
                   "kurzfr_kredite", "commercial_paper")


def _schulden_stichtag(fd: Finanzdaten, datum: date, max_tage: int = 400) -> date | None:
    """Stichtag mit Schuldenangaben: ``datum`` selbst oder der letzte frühere (höchstens ``max_tage`` zurück)."""
    kandidaten = [w.ende for k in SCHULD_KONZEPTE for w in fd.bilanz.get(k, [])
                  if -max_tage <= (w.ende - datum).days <= 5]
    if not kandidaten:
        return None
    nah = [d for d in kandidaten if abs((d - datum).days) <= 5]
    return min(nah, key=lambda d: abs((d - datum).days)) if nah else max(kandidaten)


def liquide_mittel(fd: Finanzdaten, datum: date) -> tuple[float | None, str]:
    """Cash + kurzfristige Wertpapiere zum Stichtag."""
    c = bilanzwert(fd, "cash", datum)
    if c is None:
        return None, ""
    w = bilanzwert(fd, "kurzfr_wertpapiere", datum)
    return c.wert + (w.wert if w else 0.0), _quellen(c, w)


def marktkapitalisierung(fd: Finanzdaten) -> tuple[float | None, str | None, str]:
    """Liefert (Marktkap., Grund falls nicht berechenbar, Quelle)."""
    if fd.kurs_aktuell is None:
        return None, "kein aktueller Kurs verfügbar", ""
    if fd.aktien_aktuell is None:
        return None, "keine Aktienanzahl verfügbar", ""
    if fd.kurs_waehrung and fd.kurs_waehrung != fd.waehrung:
        return None, (f"Kurs in {fd.kurs_waehrung}, Bericht in {fd.waehrung} – "
                      "ohne Währungsumrechnung nicht vergleichbar"), ""
    mk = fd.aktien_aktuell.wert * fd.kurs_aktuell.wert
    return mk, None, _quellen(fd.aktien_aktuell, fd.kurs_aktuell)


def _kurs_am(kurse: pd.Series, datum: date) -> float | None:
    """Letzter Schlusskurs an oder vor ``datum`` (höchstens 7 Tage zurück)."""
    if kurse is None or kurse.empty:
        return None
    ts = pd.Timestamp(datum)
    vorher = kurse.loc[:ts]
    if vorher.empty or (ts - vorher.index[-1]).days > 7:
        return None
    return float(vorher.iloc[-1])


def _ttm(fd: Finanzdaten, konzept: str) -> Wert | None:
    return fd.ttm.get(konzept)


def _ttm_hinweis(fd: Finanzdaten) -> str:
    return "letztes Geschäftsjahr statt 12 Monate (keine Quartalsdaten)" if fd.ttm_ist_geschaeftsjahr else ""


def _fcf_jahr(fd: Finanzdaten, ende: date) -> tuple[float | None, list[Wert]]:
    ocf, capex = jahreswert(fd, "ocf", ende), jahreswert(fd, "capex", ende)
    if ocf is None or capex is None:
        return None, []
    return ocf.wert - capex.wert, [ocf, capex]


# ---------------------------------------------------------------------
# A. Sicherheitsmarge und Abwärtsschutz
# ---------------------------------------------------------------------

def fcf_rendite(fd: Finanzdaten) -> Ergebnis:
    e = Ergebnis("fcf_rendite", hinweis=_ttm_hinweis(fd))
    ocf, capex = _ttm(fd, "ocf"), _ttm(fd, "capex")
    if ocf is None:
        e.grund = "operativer Cashflow nicht gefunden"
        return e
    if capex is None:
        e.grund = "Investitionen (Capex) nicht gefunden"
        return e
    mk, grund, mk_quelle = marktkapitalisierung(fd)
    if mk is None:
        e.grund = grund
        return e
    fcf = ocf.wert - capex.wert
    e.rohwert = fcf / mk * 100
    e.quelle = _quellen(ocf, capex) + "; " + mk_quelle
    e.datenstand = _iso(ocf.ende)
    e.details = (f"FCF {betrag(fcf, fd.waehrung)} (OCF {betrag(ocf.wert, fd.waehrung)} – Capex "
                 f"{betrag(capex.wert, fd.waehrung)}) ÷ Marktkap. {betrag(mk, fd.waehrung)}")
    return e


def ev_ebit_historie(fd: Finanzdaten) -> Ergebnis:
    e = Ergebnis("ev_ebit_historie", hinweis=_ttm_hinweis(fd))
    ebit = _ttm(fd, "ebit")
    tag = stichtag(fd)
    if ebit is None or tag is None:
        e.grund = "EBIT oder Bilanz nicht gefunden"
        return e
    if ebit.wert <= 0:
        e.grund = "EBIT der letzten 12 Monate negativ – EV/EBIT nicht sinnvoll"
        return e
    mk, grund, mk_quelle = marktkapitalisierung(fd)
    if mk is None:
        e.grund = grund
        return e
    cash, _ = liquide_mittel(fd, tag)
    if cash is None:
        e.grund = "Cash nicht gefunden"
        return e
    schulden, schulden_quelle = finanzschulden(fd, tag)
    ev = mk + schulden - cash
    aktuell = ev / ebit.wert

    historie = []
    for ende in geschaeftsjahre(fd, "ebit", 10):
        eb = jahreswert(fd, "ebit", ende)
        aktien = jahreswert(fd, "aktien_verwaessert", ende)
        kurs = _kurs_am(fd.kurse, ende)
        c, _ = liquide_mittel(fd, ende)
        if eb is None or eb.wert <= 0 or aktien is None or kurs is None or c is None:
            continue
        s, _ = finanzschulden(fd, ende)
        historie.append((aktien.wert * kurs + s - c) / eb.wert)
    if len(historie) < 5:
        e.grund = f"nur {len(historie)} Jahre mit EV/EBIT-Historie (mindestens 5 nötig)"
        return e
    median = statistics.median(historie)
    e.rohwert = (aktuell / median - 1) * 100
    e.quelle = f"{_quellen(ebit)}; {schulden_quelle}; {mk_quelle}; historische Kurse: {fd.kurs_quelle}"
    e.datenstand = _iso(max(ebit.ende, tag))
    e.details = (f"aktuell EV/EBIT {zahl(aktuell)} (EV {betrag(ev, fd.waehrung)} ÷ EBIT "
                 f"{betrag(ebit.wert, fd.waehrung)}), Median {len(historie)} Geschäftsjahre {zahl(median)}")
    return e


def ausschuettungsrendite(fd: Finanzdaten) -> Ergebnis:
    e = Ergebnis("ausschuettungsrendite", hinweis=_ttm_hinweis(fd))
    mk, grund, mk_quelle = marktkapitalisierung(fd)
    if mk is None:
        e.grund = grund
        return e
    div, rk, aus = _ttm(fd, "dividenden"), _ttm(fd, "rueckkaeufe"), _ttm(fd, "aktienausgabe")
    fehlend = [n for n, w in (("Dividenden", div), ("Rückkäufe", rk), ("Aktienausgabe", aus)) if w is None]
    d = div.wert if div else 0.0
    r = rk.wert if rk else 0.0
    a = aus.wert if aus else 0.0
    e.rohwert = (d + r - a) / mk * 100
    e.quelle = "; ".join(x for x in (_quellen(div, rk, aus), mk_quelle) if x)
    stand = [w.ende for w in (div, rk, aus) if w]
    e.datenstand = _iso(max(stand)) if stand else _iso(fd.kurs_aktuell.ende if fd.kurs_aktuell else None)
    e.details = (f"Dividenden {betrag(d, fd.waehrung)} + Rückkäufe {betrag(r, fd.waehrung)} – Ausgabe "
                 f"{betrag(a, fd.waehrung)} ÷ Marktkap. {betrag(mk, fd.waehrung)} "
                 f"(Dividendenrendite {prozent(d / mk * 100, 2)}, Netto-Rückkaufquote {prozent((r - a) / mk * 100, 2)})")
    if fehlend:
        e.hinweis = "; ".join(x for x in (e.hinweis, "nicht ausgewiesen, als 0 gezählt: " + ", ".join(fehlend)) if x)
    return e


def max_kursrueckgang(fd: Finanzdaten, jahre: int = 5) -> Ergebnis:
    e = Ergebnis("max_kursrueckgang")
    if fd.kurse is None or fd.kurse.empty:
        e.grund = "keine Kursdaten"
        return e
    ende = fd.kurse.index[-1]
    beginn = ende - pd.DateOffset(years=jahre)
    reihe = fd.kurse.loc[beginn:]
    if (reihe.index[-1] - reihe.index[0]).days < 365 * jahre - 30:
        e.grund = f"Kurshistorie kürzer als {jahre} Jahre"
        return e
    hoch = reihe.cummax()
    rueckgang = 1 - reihe / hoch
    tief_datum = rueckgang.idxmax()
    hoch_datum = reihe.loc[:tief_datum].idxmax()
    e.rohwert = float(rueckgang.max()) * 100
    e.quelle = fd.kurs_quelle
    e.datenstand = _iso(ende.date())
    e.details = (f"Hoch {zahl(float(reihe[hoch_datum]), 2)} am {hoch_datum.date():%d.%m.%Y} → "
                 f"Tief {zahl(float(reihe[tief_datum]), 2)} am {tief_datum.date():%d.%m.%Y}")
    return e


# ---------------------------------------------------------------------
# B. Langfristiges Wachstum
# ---------------------------------------------------------------------

def _jahr_davor(fd: Finanzdaten, konzept: str, ende: date, jahre: int) -> Wert | None:
    ziel = ende - timedelta(days=round(365.25 * jahre))
    return wert_am(fd.jahre.get(konzept), ziel, toleranz=20)


def umsatz_cagr(fd: Finanzdaten, jahre: int = 5) -> Ergebnis:
    e = Ergebnis("umsatz_cagr")
    enden = geschaeftsjahre(fd, "umsatz", 1)
    if not enden:
        e.grund = "Umsatz nicht gefunden"
        return e
    jetzt = jahreswert(fd, "umsatz", enden[-1])
    frueher = _jahr_davor(fd, "umsatz", jetzt.ende, jahre)
    if frueher is None:
        e.grund = f"kein Umsatz von vor {jahre} Jahren gefunden"
        return e
    if frueher.wert <= 0 or jetzt.wert <= 0:
        e.grund = "Umsatz nicht positiv – Wachstumsrate nicht sinnvoll"
        return e
    e.rohwert = ((jetzt.wert / frueher.wert) ** (1 / jahre) - 1) * 100
    e.quelle = _quellen(jetzt, frueher)
    e.datenstand = _iso(jetzt.ende)
    e.details = (f"GJ {jetzt.ende:%m/%Y}: {betrag(jetzt.wert, fd.waehrung)}, "
                 f"GJ {frueher.ende:%m/%Y}: {betrag(frueher.wert, fd.waehrung)}")
    return e


def fcf_je_aktie_cagr(fd: Finanzdaten, jahre: int = 5) -> Ergebnis:
    e = Ergebnis("fcf_je_aktie_cagr")
    enden = geschaeftsjahre(fd, "ocf", 1)
    if not enden:
        e.grund = "operativer Cashflow nicht gefunden"
        return e
    ende_jetzt = enden[-1]
    ziel = ende_jetzt - timedelta(days=round(365.25 * jahre))
    ende_frueher = next((w.ende for w in fd.jahre.get("ocf", []) if _nahe(w.ende, ziel, 20)), None)
    if ende_frueher is None:
        e.grund = f"kein Cashflow von vor {jahre} Jahren gefunden"
        return e
    werte = {}
    quellen = []
    for ende in (ende_frueher, ende_jetzt):
        fcf, teile = _fcf_jahr(fd, ende)
        aktien = jahreswert(fd, "aktien_verwaessert", ende)
        if fcf is None or aktien is None or aktien.wert <= 0:
            e.grund = f"FCF oder verwässerte Aktienanzahl für GJ {ende:%m/%Y} fehlt"
            return e
        werte[ende] = fcf / aktien.wert
        quellen += teile + [aktien]
    alt, neu = werte[ende_frueher], werte[ende_jetzt]
    if alt <= 0 or neu <= 0:
        e.grund = f"FCF je Aktie nicht positiv ({zahl(alt, 2)} → {zahl(neu, 2)}) – Wachstumsrate nicht sinnvoll"
        return e
    e.rohwert = ((neu / alt) ** (1 / jahre) - 1) * 100
    e.quelle = _quellen(*quellen)
    e.datenstand = _iso(ende_jetzt)
    e.details = (f"FCF je Aktie GJ {ende_jetzt:%m/%Y}: {zahl(neu, 2)} {fd.waehrung}, "
                 f"GJ {ende_frueher:%m/%Y}: {zahl(alt, 2)} {fd.waehrung}")
    return e


def umsatz_bestaendigkeit(fd: Finanzdaten, jahre: int = 10) -> Ergebnis:
    e = Ergebnis("umsatz_bestaendigkeit")
    enden = geschaeftsjahre(fd, "umsatz", jahre + 1)
    reihe = [jahreswert(fd, "umsatz", d) for d in enden]
    paare = [(a, b) for a, b in zip(reihe, reihe[1:]) if 330 <= (b.ende - a.ende).days <= 400]
    if len(paare) < 5:
        e.grund = f"nur {len(paare)} Jahresvergleiche möglich (mindestens 5 nötig)"
        return e
    plus = sum(1 for a, b in paare if b.wert > a.wert)
    if len(paare) < jahre:
        e.rohwert = plus * jahre / len(paare)
        e.hinweis = f"hochgerechnet aus {plus} von {len(paare)} Jahren"
    else:
        e.rohwert = float(plus)
    e.quelle = _quellen(*reihe)
    e.datenstand = _iso(reihe[-1].ende)
    e.details = f"{plus} von {len(paare)} Jahren mit Umsatzplus (GJ {paare[0][1].ende:%Y}–{paare[-1][1].ende:%Y})"
    return e


# ---------------------------------------------------------------------
# C. Qualität und Kapitalrendite
# ---------------------------------------------------------------------

STEUER_STANDARD = 0.21
STEUER_MAX = 0.35


def steuersatz(fd: Finanzdaten, ende: date) -> float:
    """Effektiver Steuersatz, begrenzt auf 0–35 %. Ohne sinnvolle Daten: 21 %."""
    st, vor = jahreswert(fd, "steuern", ende), jahreswert(fd, "vorsteuergewinn", ende)
    if st is None or vor is None or vor.wert <= 0:
        return STEUER_STANDARD
    return min(max(st.wert / vor.wert, 0.0), STEUER_MAX)


def roic(fd: Finanzdaten, jahre: int = 5) -> Ergebnis:
    e = Ergebnis("roic")
    werte, quellen, texte = [], [], []
    for ende in geschaeftsjahre(fd, "ebit", jahre):
        ebit = jahreswert(fd, "ebit", ende)
        ek = bilanzwert(fd, "eigenkapital", ende)
        cash, _ = liquide_mittel(fd, ende)
        if ebit is None or ek is None or cash is None:
            continue
        schulden, _ = finanzschulden(fd, ende)
        kapital = ek.wert + schulden - cash
        if kapital <= 0:
            texte.append(f"GJ {ende:%Y}: investiertes Kapital ≤ 0, übersprungen")
            continue
        t = steuersatz(fd, ende)
        r = ebit.wert * (1 - t) / kapital * 100
        werte.append(r)
        quellen += [ebit, ek]
        texte.append(f"GJ {ende:%Y}: {prozent(r)} (Steuersatz {prozent(t * 100, 0)})")
    if len(werte) < 3:
        e.grund = f"nur {len(werte)} Jahre berechenbar (mindestens 3 nötig)"
        e.details = ", ".join(texte)
        return e
    e.rohwert = sum(werte) / len(werte)
    e.quelle = _quellen(*quellen) + "; Finanzschulden und Cash aus der Bilanz"
    e.datenstand = _iso(quellen[-2].ende)
    e.details = ", ".join(texte)
    if len(werte) < jahre:
        e.hinweis = f"Durchschnitt aus {len(werte)} Jahren"
    return e


def bruttomarge_stabilitaet(fd: Finanzdaten, jahre: int = 10) -> Ergebnis:
    e = Ergebnis("bruttomarge_stabilitaet")
    margen, quellen = [], []
    for ende in geschaeftsjahre(fd, "umsatz", jahre):
        u = jahreswert(fd, "umsatz", ende)
        bg = jahreswert(fd, "bruttogewinn", ende)
        if bg is None:
            hk = jahreswert(fd, "herstellkosten", ende)
            if hk is None:
                continue
            brutto, quelle_bg = u.wert - hk.wert, hk
        else:
            brutto, quelle_bg = bg.wert, bg
        if u.wert <= 0:
            continue
        margen.append((ende, brutto / u.wert * 100))
        quellen += [u, quelle_bg]
    if len(margen) < 5:
        e.grund = f"Bruttomarge nur für {len(margen)} Jahre berechenbar (mindestens 5 nötig)"
        return e
    e.rohwert = statistics.stdev(m for _, m in margen)
    e.quelle = _quellen(*quellen)
    e.datenstand = _iso(margen[-1][0])
    e.details = "Bruttomargen: " + ", ".join(f"{d:%Y} {prozent(m)}" for d, m in margen)
    if len(margen) < jahre:
        e.hinweis = f"aus {len(margen)} Jahren"
    return e


def fcf_umwandlung(fd: Finanzdaten, jahre: int = 5) -> Ergebnis:
    e = Ergebnis("fcf_umwandlung")
    summe_fcf = summe_ng = 0.0
    n, quellen, letztes = 0, [], None
    for ende in geschaeftsjahre(fd, "ocf", jahre):
        fcf, teile = _fcf_jahr(fd, ende)
        ng = jahreswert(fd, "nettogewinn", ende)
        if fcf is None or ng is None:
            continue
        summe_fcf += fcf
        summe_ng += ng.wert
        n += 1
        quellen += teile + [ng]
        letztes = ende
    if n < 3:
        e.grund = f"nur {n} Jahre mit FCF und Nettogewinn (mindestens 3 nötig)"
        return e
    if summe_ng <= 0:
        e.grund = "Nettogewinn über den Zeitraum nicht positiv – Verhältnis nicht sinnvoll"
        return e
    e.rohwert = summe_fcf / summe_ng * 100
    e.quelle = _quellen(*quellen)
    e.datenstand = _iso(letztes)
    e.details = f"Summe FCF {betrag(summe_fcf, fd.waehrung)} ÷ Summe Nettogewinn {betrag(summe_ng, fd.waehrung)} ({n} Jahre)"
    return e


# ---------------------------------------------------------------------
# D. Gesunde Bilanz
# ---------------------------------------------------------------------

def nettoverschuldung_ebitda(fd: Finanzdaten) -> Ergebnis:
    e = Ergebnis("nettoverschuldung_ebitda", hinweis=_ttm_hinweis(fd))
    tag = stichtag(fd)
    if tag is None:
        e.grund = "Bilanz nicht gefunden"
        return e
    cash, cash_quelle = liquide_mittel(fd, tag)
    if cash is None:
        e.grund = "Cash nicht gefunden"
        return e
    schulden, schulden_quelle = finanzschulden(fd, tag)
    netto = schulden - cash
    ebit, abschr = _ttm(fd, "ebit"), _ttm(fd, "abschreibungen")
    ebitda = ebit.wert + abschr.wert if (ebit and abschr) else None
    e.quelle = "; ".join(x for x in (schulden_quelle, cash_quelle, _quellen(ebit, abschr)) if x)
    e.datenstand = _iso(tag)
    e.details = (f"Finanzschulden {betrag(schulden, fd.waehrung)} – Cash {betrag(cash, fd.waehrung)} = "
                 f"{betrag(netto, fd.waehrung)}; EBITDA {betrag(ebitda, fd.waehrung)}")
    if netto <= 0:
        e.fixpunkte = 10.0
        e.rohwert = netto / ebitda if ebitda and ebitda > 0 else None
        e.hinweis = "; ".join(x for x in (e.hinweis, "Nettocash → 10 Punkte") if x)
        return e
    if ebitda is None:
        e.grund = "EBIT oder Abschreibungen nicht gefunden"
        return e
    if ebitda <= 0:
        e.grund = "EBITDA negativ – Verhältnis nicht sinnvoll"
        return e
    e.rohwert = netto / ebitda
    return e


def zinsdeckung(fd: Finanzdaten) -> Ergebnis:
    e = Ergebnis("zinsdeckung", hinweis=_ttm_hinweis(fd))
    ebit, zins = _ttm(fd, "ebit"), _ttm(fd, "zinsaufwand")
    if ebit is None:
        e.grund = "EBIT nicht gefunden"
        return e
    e.datenstand = _iso(ebit.ende)
    if zins is None or zins.wert <= 0:
        tag = stichtag(fd)
        schulden = finanzschulden(fd, tag)[0] if tag else 0.0
        if schulden > 0:
            e.quelle = _quellen(ebit)
            e.grund = (f"Zinsaufwand nicht (mehr) separat ausgewiesen, obwohl Finanzschulden von "
                       f"{betrag(schulden, fd.waehrung)} bestehen")
            return e
        e.fixpunkte = 10.0
        e.quelle = _quellen(ebit)
        e.details = f"EBIT {betrag(ebit.wert, fd.waehrung)}, kein Zinsaufwand ausgewiesen"
        e.hinweis = "; ".join(x for x in (e.hinweis, "ohne Zinsaufwand → 10 Punkte") if x)
        return e
    e.rohwert = ebit.wert / zins.wert
    e.quelle = _quellen(ebit, zins)
    e.details = f"EBIT {betrag(ebit.wert, fd.waehrung)} ÷ Zinsaufwand {betrag(zins.wert, fd.waehrung)}"
    return e


def current_ratio(fd: Finanzdaten) -> Ergebnis:
    e = Ergebnis("current_ratio")
    tag = stichtag(fd)
    uv = bilanzwert(fd, "umlaufvermoegen", tag) if tag else None
    kv = bilanzwert(fd, "kurzfr_verbindlichkeiten", tag) if tag else None
    if uv is None or kv is None:
        e.grund = "Umlaufvermögen oder kurzfristige Verbindlichkeiten nicht ausgewiesen (z. B. bei Banken üblich)"
        return e
    if kv.wert <= 0:
        e.grund = "kurzfristige Verbindlichkeiten ≤ 0"
        return e
    e.rohwert = uv.wert / kv.wert
    e.quelle = _quellen(uv, kv)
    e.datenstand = _iso(tag)
    e.details = f"Umlaufvermögen {betrag(uv.wert, fd.waehrung)} ÷ kurzfr. Verbindlichkeiten {betrag(kv.wert, fd.waehrung)}"
    return e


def altman_z(fd: Finanzdaten) -> Ergebnis:
    """Altman Z-Score, Originalformel von 1968 (passt zu den Zonen 3,0 / 1,8)."""
    e = Ergebnis("altman_z", hinweis=_ttm_hinweis(fd))
    tag = stichtag(fd)
    if tag is None:
        e.grund = "Bilanz nicht gefunden"
        return e
    b = lambda k: bilanzwert(fd, k, tag)  # noqa: E731
    ta, uv, kv, re_ = b("bilanzsumme"), b("umlaufvermoegen"), b("kurzfr_verbindlichkeiten"), b("gewinnruecklagen")
    tl = b("verbindlichkeiten")
    tl_wert = tl.wert if tl else None
    if tl is None and ta is not None and b("eigenkapital") is not None:
        tl_wert = ta.wert - b("eigenkapital").wert
    ebit, umsatz = _ttm(fd, "ebit"), _ttm(fd, "umsatz")
    fehlend = [n for n, w in (("Bilanzsumme", ta), ("Umlaufvermögen", uv), ("kurzfr. Verbindlichkeiten", kv),
                              ("Gewinnrücklagen", re_), ("EBIT", ebit), ("Umsatz", umsatz)) if w is None]
    if tl_wert is None:
        fehlend.append("Verbindlichkeiten")
    if fehlend:
        e.grund = "fehlt: " + ", ".join(fehlend)
        return e
    mk, grund, mk_quelle = marktkapitalisierung(fd)
    if mk is None:
        e.grund = grund
        return e
    if ta.wert <= 0 or tl_wert <= 0:
        e.grund = "Bilanzsumme oder Verbindlichkeiten ≤ 0"
        return e
    x1 = (uv.wert - kv.wert) / ta.wert
    x2 = re_.wert / ta.wert
    x3 = ebit.wert / ta.wert
    x4 = mk / tl_wert
    x5 = umsatz.wert / ta.wert
    e.rohwert = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5
    e.quelle = _quellen(ta, uv, kv, re_, tl, ebit, umsatz) + "; " + mk_quelle
    e.datenstand = _iso(tag)
    e.details = (f"X1 WC/TA {zahl(x1, 3)}, X2 RE/TA {zahl(x2, 3)}, X3 EBIT/TA {zahl(x3, 3)}, "
                 f"X4 MK/TL {zahl(x4, 3)}, X5 Umsatz/TA {zahl(x5, 3)}")
    return e


ALLE = [
    fcf_rendite, ev_ebit_historie, ausschuettungsrendite, max_kursrueckgang,
    umsatz_cagr, fcf_je_aktie_cagr, umsatz_bestaendigkeit,
    roic, bruttomarge_stabilitaet, fcf_umwandlung,
    nettoverschuldung_ebitda, zinsdeckung, current_ratio, altman_z,
]


def alle_berechnen(fd: Finanzdaten) -> list[Ergebnis]:
    ergebnisse = []
    for funktion in ALLE:
        try:
            ergebnisse.append(funktion(fd))
        except Exception as ex:  # eine kaputte Kennzahl darf die Analyse nicht stoppen
            ergebnisse.append(Ergebnis(funktion.__name__, grund=f"Rechenfehler: {ex}"))
    return ergebnisse
