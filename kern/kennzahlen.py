"""Berechnung der Kennzahlen der Kategorien A–D.

Dieses Modul kennt weder die SEC noch die Oberfläche. Es bekommt fertig
aufbereitete Werte (``Finanzdaten``) und liefert pro Kennzahl ein
``Ergebnis`` mit Rohwert, Quelle, Datenstand und ggf. dem Grund, warum
die Kennzahl ausgelassen wurde. Dadurch ist alles einzeln testbar.

Begriffe ("Konzepte") für die Eingangswerte:
  Zeitraumwerte (ttm = letzte 12 Monate, jahre = Geschäftsjahre):
    umsatz, bruttogewinn, herstellkosten, ebit, nettogewinn, ocf, capex,
    abschreibungen, zinsaufwand, steuern, vorsteuergewinn, dividenden,
    rueckkaeufe, aktienausgabe, aktien_verwaessert, aktienverguetung
  Stichtagswerte (bilanz):
    bilanzsumme, umlaufvermoegen, kurzfr_verbindlichkeiten, verbindlichkeiten,
    eigenkapital, gewinnruecklagen, cash, kurzfr_wertpapiere, langfr_wertpapiere,
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
    # Einstellungen (aus config/schwellen.yaml, Abschnitt "optionen")
    fcf_abzug_aktienverguetung: bool = True
    wachstum_min: float = -5.0                    # Grenzen für das Wachstum in der erwarteten Rendite (%)
    wachstum_max: float = 12.0


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
    teile = schulden_teile(fd, datum)
    if teile is None:
        return 0.0, "keine Finanzschulden ausgewiesen"
    lang_teil, kurz_teil, quelle = teile
    return lang_teil + kurz_teil, quelle


def schulden_teile(fd: Finanzdaten, datum: date) -> tuple[float, float, str] | None:
    """(langfristiger Teil, kurzfristiger Teil, Quelle) der Finanzschulden, Regeln siehe ``finanzschulden``."""
    stand = _schulden_stichtag(fd, datum)
    if stand is None:
        return None
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
    return lang_teil, kurz_teil, quelle


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


def _fcf(fd: Finanzdaten, ocf: Wert | None, capex: Wert | None, sbc: Wert | None):
    """Free Cashflow = OCF – Capex (– Aktienvergütung, falls eingeschaltet).

    Liefert (FCF, verwendete Werte, Rechenweg-Text) oder (None, [], Grund).
    """
    if ocf is None:
        return None, [], "operativer Cashflow nicht gefunden"
    if capex is None:
        return None, [], "Investitionen (Capex) nicht gefunden"
    fcf = ocf.wert - capex.wert
    text = f"OCF {betrag(ocf.wert, fd.waehrung)} – Capex {betrag(capex.wert, fd.waehrung)}"
    teile = [ocf, capex]
    if fd.fcf_abzug_aktienverguetung:
        if sbc is not None:
            fcf -= sbc.wert
            teile.append(sbc)
            text += f" – Aktienvergütung {betrag(sbc.wert, fd.waehrung)}"
        else:
            text += " (keine Aktienvergütung ausgewiesen)"
    return fcf, teile, text


def fcf_ttm(fd: Finanzdaten):
    """Free Cashflow der letzten 12 Monate: (FCF, Werte, Text) oder (None, [], Grund)."""
    return _fcf(fd, _ttm(fd, "ocf"), _ttm(fd, "capex"), _ttm(fd, "aktienverguetung"))


def _fcf_jahr(fd: Finanzdaten, ende: date) -> tuple[float | None, list[Wert]]:
    fcf, teile, _ = _fcf(fd, jahreswert(fd, "ocf", ende), jahreswert(fd, "capex", ende),
                         jahreswert(fd, "aktienverguetung", ende))
    return fcf, teile


def _cagr(start: float, ende: float, jahre: float) -> float:
    return ((ende / start) ** (1 / jahre) - 1) * 100


def wachstum_geglaettet(fd: Finanzdaten, enden: list[date], wert_im_jahr, jahre: int = 5, fenster: int = 3):
    """Jährliches Wachstum vom Durchschnitt der ersten ``fenster`` Jahre zum Durchschnitt der letzten.

    Beispiel bei 5 Jahren: Ø GJ 2018–2020 → Ø GJ 2023–2025. Die Mitten der beiden Fenster liegen
    5 Jahre auseinander. Einzelne Ausreißerjahre verzerren das Ergebnis dadurch weniger.
    Gibt es zu wenig Jahre, wird von Jahr zu Jahr gerechnet (Hinweis "ohne Glättung").

    Liefert (CAGR in %, Rechenweg, Hinweis, Grund).
    """
    enden = sorted(enden)
    if not enden:
        return None, "", "", "keine Jahreswerte"
    jetzt = enden[-1]
    ziel_start = jetzt - timedelta(days=round(365.25 * jahre))
    # Geglättet: Fenster am Ende und gleich großes Fenster ``jahre`` Jahre davor
    if len(enden) >= jahre + fenster:
        ende_fenster = enden[-fenster:]
        start_fenster = enden[-(jahre + fenster):-jahre]
        if _nahe(start_fenster[-1], ziel_start, 20):
            a = [wert_im_jahr(d) for d in start_fenster]
            b = [wert_im_jahr(d) for d in ende_fenster]
            if None not in a and None not in b:
                sa, sb = sum(a) / fenster, sum(b) / fenster
                if sa <= 0 or sb <= 0:
                    return None, "", "", (f"Durchschnittswert nicht positiv (Ø {start_fenster[0]:%Y}–{start_fenster[-1]:%Y}: "
                                          f"{zahl(sa, 2)}, Ø {ende_fenster[0]:%Y}–{ende_fenster[-1]:%Y}: {zahl(sb, 2)})")
                text = (f"Ø GJ {start_fenster[0]:%Y}–{start_fenster[-1]:%Y}: {zahl(sa, 2)} → "
                        f"Ø GJ {ende_fenster[0]:%Y}–{ende_fenster[-1]:%Y}: {zahl(sb, 2)}")
                return _cagr(sa, sb, jahre), text, "", None
    # Ersatz: Punkt zu Punkt
    start = next((d for d in enden if _nahe(d, ziel_start, 20)), None)
    if start is None:
        return None, "", "", f"keine Werte von vor {jahre} Jahren"
    a, b = wert_im_jahr(start), wert_im_jahr(jetzt)
    if a is None or b is None:
        return None, "", "", "Werte für Anfangs- oder Endjahr fehlen"
    if a <= 0 or b <= 0:
        return None, "", "", f"Wert nicht positiv ({zahl(a, 2)} → {zahl(b, 2)}) – Wachstumsrate nicht sinnvoll"
    text = f"GJ {start:%Y}: {zahl(a, 2)} → GJ {jetzt:%Y}: {zahl(b, 2)}"
    return _cagr(a, b, jahre), text, "ohne Glättung (zu wenige Jahre)", None


# ---------------------------------------------------------------------
# A. Sicherheitsmarge und Abwärtsschutz
# ---------------------------------------------------------------------

def fcf_rendite(fd: Finanzdaten) -> Ergebnis:
    e = Ergebnis("fcf_rendite", hinweis=_ttm_hinweis(fd))
    fcf, teile, text = fcf_ttm(fd)
    if fcf is None:
        e.grund = text
        return e
    mk, grund, mk_quelle = marktkapitalisierung(fd)
    if mk is None:
        e.grund = grund
        return e
    e.rohwert = fcf / mk * 100
    e.quelle = _quellen(*teile) + "; " + mk_quelle
    e.datenstand = _iso(teile[0].ende)
    e.details = f"FCF {betrag(fcf, fd.waehrung)} ({text}) ÷ Marktkap. {betrag(mk, fd.waehrung)}"
    return e


def fcf_rendite_historie(fd: Finanzdaten) -> Ergebnis:
    """Aktuelle FCF-Rendite im Vergleich zum Median der letzten 10 Geschäftsjahre (positiv = günstiger)."""
    e = Ergebnis("fcf_rendite_historie", hinweis=_ttm_hinweis(fd))
    aktuell = fcf_rendite(fd)
    if aktuell.rohwert is None:
        e.grund = aktuell.grund
        return e
    historie = []
    for ende in geschaeftsjahre(fd, "ocf", 10):
        fcf, _ = _fcf_jahr(fd, ende)
        aktien = jahreswert(fd, "aktien_verwaessert", ende)
        kurs = _kurs_am(fd.kurse, ende)
        if fcf is None or aktien is None or kurs is None or aktien.wert <= 0:
            continue
        historie.append(fcf / (aktien.wert * kurs) * 100)
    if len(historie) < 5:
        e.grund = f"nur {len(historie)} Jahre mit FCF-Rendite-Historie (mindestens 5 nötig)"
        return e
    median = statistics.median(historie)
    if median <= 0:
        e.grund = "Median der historischen FCF-Rendite nicht positiv – Vergleich nicht sinnvoll"
        return e
    e.rohwert = (aktuell.rohwert / median - 1) * 100
    e.quelle = aktuell.quelle + f"; historische Kurse: {fd.kurs_quelle}"
    e.datenstand = aktuell.datenstand
    e.details = (f"aktuell {prozent(aktuell.rohwert, 2)}, Median {len(historie)} Geschäftsjahre "
                 f"{prozent(median, 2)} (positiv = höhere Rendite als üblich, also günstiger)")
    return e


def erwartete_rendite(fd: Finanzdaten) -> Ergebnis:
    """FCF-Rendite + nachhaltiges Wachstum je Aktie ≈ jährliche Rendite bei gleichbleibender Bewertung."""
    e = Ergebnis("erwartete_rendite", hinweis=_ttm_hinweis(fd))
    rendite = fcf_rendite(fd)
    if rendite.rohwert is None:
        e.grund = rendite.grund
        return e
    kandidaten = [(n, r.rohwert) for n, r in (("Umsatz", umsatz_cagr(fd)), ("FCF je Aktie", fcf_je_aktie_cagr(fd)))
                  if r.rohwert is not None]
    if not kandidaten:
        e.grund = "kein Wachstum berechenbar"
        return e
    name, g = min(kandidaten, key=lambda x: x[1])      # vorsichtig: das niedrigere Wachstum
    g_begrenzt = min(max(g, fd.wachstum_min), fd.wachstum_max)
    e.rohwert = rendite.rohwert + g_begrenzt
    e.quelle = rendite.quelle
    e.datenstand = rendite.datenstand
    e.details = (f"FCF-Rendite {prozent(rendite.rohwert, 2)} + Wachstum {prozent(g_begrenzt, 1)} "
                 f"(niedrigerer Wert aus {', '.join(f'{n} {prozent(v)}' for n, v in kandidaten)}"
                 + (f", begrenzt auf {zahl(fd.wachstum_min, 0)} bis {zahl(fd.wachstum_max, 0)} %" if g != g_begrenzt else "")
                 + ")")
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
    liste = fd.jahre.get("umsatz") or []
    if not liste:
        e.grund = "Umsatz nicht gefunden"
        return e

    def wert(d):
        w = jahreswert(fd, "umsatz", d)
        return w.wert / 1e9 if w else None

    cagr, text, hinweis, grund = wachstum_geglaettet(fd, [w.ende for w in liste], wert, jahre)
    if grund:
        e.grund = grund
        return e
    e.rohwert, e.hinweis = cagr, hinweis
    e.quelle = _quellen(*liste[-8:])
    e.datenstand = _iso(liste[-1].ende)
    e.details = f"Umsatz in Mrd. {fd.waehrung}: {text}"
    return e


def fcf_je_aktie_cagr(fd: Finanzdaten, jahre: int = 5) -> Ergebnis:
    e = Ergebnis("fcf_je_aktie_cagr")
    enden = [w.ende for w in fd.jahre.get("ocf", [])]
    if not enden:
        e.grund = "operativer Cashflow nicht gefunden"
        return e
    quellen = []

    def wert(d):
        fcf, teile = _fcf_jahr(fd, d)
        aktien = jahreswert(fd, "aktien_verwaessert", d)
        if fcf is None or aktien is None or aktien.wert <= 0:
            return None
        quellen.extend(teile + [aktien])
        return fcf / aktien.wert

    cagr, text, hinweis, grund = wachstum_geglaettet(fd, enden, wert, jahre)
    if grund:
        e.grund = "FCF je Aktie: " + grund
        return e
    e.rohwert, e.hinweis = cagr, hinweis
    e.quelle = _quellen(*quellen)
    e.datenstand = _iso(max(enden))
    e.details = f"FCF je Aktie in {fd.waehrung}: {text}"
    return e


def aktien_verwaesserung(fd: Finanzdaten, jahre: int = 5) -> Ergebnis:
    """Jährliche Veränderung der verwässerten Aktienanzahl (negativ = Rückkäufe, positiv = Verwässerung)."""
    e = Ergebnis("aktien_verwaesserung")
    liste = fd.jahre.get("aktien_verwaessert") or []
    if not liste:
        e.grund = "verwässerte Aktienanzahl nicht gefunden"
        return e
    jetzt = liste[-1]
    frueher = _jahr_davor(fd, "aktien_verwaessert", jetzt.ende, jahre)
    if frueher is None or frueher.wert <= 0:
        e.grund = f"keine Aktienanzahl von vor {jahre} Jahren"
        return e
    e.rohwert = _cagr(frueher.wert, jetzt.wert, jahre)
    e.quelle = _quellen(frueher, jetzt)
    e.datenstand = _iso(jetzt.ende)
    e.details = (f"GJ {frueher.ende:%Y}: {zahl(frueher.wert / 1e6, 1)} Mio. → "
                 f"GJ {jetzt.ende:%Y}: {zahl(jetzt.wert / 1e6, 1)} Mio. Aktien (verwässert, splitbereinigt)")
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


def investiertes_kapital(fd: Finanzdaten, datum: date) -> tuple[float | None, str]:
    """Betrieblich gebundenes Kapital, berechnet über die Aktivseite.

    = Bilanzsumme – Cash – Wertpapiere (kurz- und langfristig)
      – nicht zinstragende kurzfristige Verbindlichkeiten
    Funktioniert auch bei negativem Eigenkapital (z. B. nach hohen Aktienrückkäufen).
    Fehlen die kurzfristigen Verbindlichkeiten (Banken), ersatzweise Eigenkapital + Schulden – Cash.
    """
    ta = bilanzwert(fd, "bilanzsumme", datum)
    kv = bilanzwert(fd, "kurzfr_verbindlichkeiten", datum)
    cash, _ = liquide_mittel(fd, datum)
    if ta is not None and kv is not None and cash is not None:
        lw = bilanzwert(fd, "langfr_wertpapiere", datum)
        teile = schulden_teile(fd, datum)
        kurz_schulden = teile[1] if teile else 0.0
        return ta.wert - cash - (lw.wert if lw else 0.0) - (kv.wert - kurz_schulden), "Aktivseite"
    ek = bilanzwert(fd, "eigenkapital", datum)
    if ek is not None and cash is not None:
        return ek.wert + finanzschulden(fd, datum)[0] - cash, "Eigenkapital + Schulden – Cash"
    return None, ""


def roic(fd: Finanzdaten, jahre: int = 5) -> Ergebnis:
    e = Ergebnis("roic")
    werte, quellen, texte, methoden = [], [], [], set()
    for ende in geschaeftsjahre(fd, "ebit", jahre):
        ebit = jahreswert(fd, "ebit", ende)
        kapital, methode = investiertes_kapital(fd, ende)
        if ebit is None or kapital is None:
            continue
        vorjahr, _ = investiertes_kapital(fd, ende - timedelta(days=365))
        if vorjahr is not None and vorjahr > 0:
            kapital = (kapital + vorjahr) / 2          # Durchschnitt aus Jahresanfang und -ende
        if kapital <= 0:
            texte.append(f"GJ {ende:%Y}: investiertes Kapital ≤ 0, übersprungen")
            continue
        t = steuersatz(fd, ende)
        r = ebit.wert * (1 - t) / kapital * 100
        werte.append(r)
        methoden.add(methode)
        quellen.append(ebit)
        texte.append(f"GJ {ende:%Y}: {prozent(r)} (Steuersatz {prozent(t * 100, 0)})")
    if len(werte) < 3:
        e.grund = f"nur {len(werte)} Jahre berechenbar (mindestens 3 nötig)"
        e.details = ", ".join(texte)
        return e
    e.rohwert = sum(werte) / len(werte)
    e.quelle = _quellen(*quellen) + "; investiertes Kapital aus der Bilanz (" + ", ".join(sorted(methoden)) + ")"
    e.datenstand = _iso(quellen[-1].ende)
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


def entschuldungsdauer(fd: Finanzdaten) -> Ergebnis:
    """Jahre, die der Free Cashflow bräuchte, um die Nettoschulden zu tilgen."""
    e = Ergebnis("entschuldungsdauer", hinweis=_ttm_hinweis(fd))
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
    fcf, teile, text = fcf_ttm(fd)
    e.quelle = "; ".join(x for x in (schulden_quelle, cash_quelle, _quellen(*teile)) if x)
    e.datenstand = _iso(tag)
    if netto <= 0:
        e.fixpunkte = 10.0
        e.rohwert = 0.0
        e.details = f"Nettocash {betrag(-netto, fd.waehrung)}"
        e.hinweis = "; ".join(x for x in (e.hinweis, "Nettocash → 10 Punkte") if x)
        return e
    if fcf is None:
        e.grund = text
        return e
    e.details = f"Nettoschulden {betrag(netto, fd.waehrung)} ÷ FCF {betrag(fcf, fd.waehrung)} ({text})"
    if fcf <= 0:
        e.fixpunkte = 0.0
        e.hinweis = "; ".join(x for x in (e.hinweis, "negativer Free Cashflow bei Nettoschulden → 0 Punkte") if x)
        return e
    e.rohwert = netto / fcf
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
    fcf_rendite, fcf_rendite_historie, ev_ebit_historie, ausschuettungsrendite, max_kursrueckgang, erwartete_rendite,
    umsatz_cagr, fcf_je_aktie_cagr, umsatz_bestaendigkeit,
    roic, bruttomarge_stabilitaet, fcf_umwandlung, aktien_verwaesserung,
    nettoverschuldung_ebitda, zinsdeckung, entschuldungsdauer, altman_z,
]


def alle_berechnen(fd: Finanzdaten) -> list[Ergebnis]:
    ergebnisse = []
    for funktion in ALLE:
        try:
            ergebnisse.append(funktion(fd))
        except Exception as ex:  # eine kaputte Kennzahl darf die Analyse nicht stoppen
            ergebnisse.append(Ergebnis(funktion.__name__, grund=f"Rechenfehler: {ex}"))
    return ergebnisse
