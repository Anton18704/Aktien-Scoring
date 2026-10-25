# Aktien-Scoring – Anleitung

Eine lokale Web-App, die US-Aktien in fünf Kategorien bewertet und alles in einer
Datei (`aktien.db`) auf deinem Laptop speichert.

---

## 1. Einmalig einrichten (Windows)

**a) Python installieren**
1. https://www.python.org/downloads/ öffnen und „Download Python 3.13“ klicken.
2. Installer starten. **Wichtig:** unten das Häkchen bei **„Add python.exe to PATH“** setzen.
3. „Install Now“ klicken.

**b) Git installieren** (um den Code von GitHub zu holen)
1. https://git-scm.com/download/win öffnen, Installer herunterladen und mit den
   Standard-Einstellungen durchklicken.

**c) Code auf den Desktop holen**
1. Auf dem Desktop den Ordner **Claude Code** anlegen (falls noch nicht vorhanden).
2. Den Ordner öffnen, oben in die Adresszeile `cmd` tippen und Enter drücken.
   Es öffnet sich ein schwarzes Fenster in genau diesem Ordner.
3. Dort eingeben:
   ```
   git clone https://github.com/Anton18704/Aktien-Scoring.git
   ```
4. Jetzt gibt es `Desktop\Claude Code\aktien-scoring`.

## 2. Starten

- Im Ordner `aktien-scoring` auf **`start.bat`** doppelklicken.
- Beim **ersten Start** werden die nötigen Pakete installiert (einige Minuten).
- Danach öffnet sich der Browser mit `http://localhost:8501`.
- Das schwarze Fenster offen lassen, solange du die App nutzt. Zum Beenden schließen.
- Beim ersten Start fragt die App auf der Seite **Einstellungen** nach deiner
  Kontakt-E-Mail für die SEC. Eintragen und speichern – sie landet in
  `config/settings.toml` (wird nicht zu GitHub hochgeladen).

## 3. Vom iPad aus nutzen

1. Laptop und iPad müssen im **selben WLAN** sein.
2. `start.bat` auf dem Laptop starten. Im schwarzen Fenster steht
   „Auf dem iPad: http://192.168.x.x:8501“.
3. Diese Adresse in Safari auf dem iPad eintippen. Tipp: „Zum Home-Bildschirm“
   hinzufügen, dann hast du ein App-Symbol.
4. Fragt Windows beim ersten Start „Zugriff zulassen?“ (Windows-Firewall):
   **„Private Netzwerke“ ankreuzen** und zulassen. Ohne das kommt das iPad nicht durch.
5. Klappt es nicht: Prüfen, ob dein WLAN in Windows als **„Privates Netzwerk“**
   eingestellt ist (Einstellungen → Netzwerk und Internet → WLAN → dein Netz).
6. Der Laptop darf nicht im Ruhezustand sein, solange du am iPad arbeitest.

> Die App hat kein Passwort. Jeder in deinem Heimnetz könnte sie öffnen.
> Im eigenen WLAN ist das in Ordnung, in öffentlichen WLANs (Café, Hotel)
> `start.bat` bitte nicht laufen lassen.

## 4. Bedienung

| Seite | Was du dort machst |
|---|---|
| **Hauptliste** | Alle Titel mit Scores. Spaltenüberschrift antippen = sortieren. Zeile antippen → Details, Neu analysieren, Löschen. „Alle Titel neu analysieren“ nach Updates. Unten: Knöpfe zur Kategorieansicht. ⛔ K.o. = eine Kategorie liegt unter der K.o.-Schwelle. |
| **Import** | Einen Ticker eingeben, oder eine CSV-Datei mit einer Spalte `Ticker` hochladen. |
| **Detailansicht** | Bei neuen Titeln zuerst deine Einschätzung (4 Regler, 1 Satz Begründung, „Ich liege falsch, wenn …“). Danach Netzdiagramm, Beiträge, alle Kennzahlen mit Rohwert, Punkten, Rechenweg, Quelle und Datenstand, Verlauf. Sektor hier von Hand ändern. |
| **Kategorieansicht** | Alle Titel nach einer Kategorie sortiert, mit den Rohwerten. |
| **Einstellungen** | Gewichte (Regler), Kategorien an/aus, Standard wiederherstellen, Schwellen ansehen, E-Mail. |

Eine erneute Analyse legt immer einen **neuen** Eintrag an. Ältere bleiben für den Verlauf erhalten.

**Nach einem Update mit neuen Kennzahlen:** in der Hauptliste „Alle Titel neu analysieren“ ausführen.
Ältere Analysen kennen die neuen Kennzahlen noch nicht; entfallene Kennzahlen werden ignoriert.

## 5. Rohwerte prüfen (AAPL, KO, CAT)

Doppelklick auf **`pruefen.bat`**. Es prüft AAPL, KO und CAT und zeigt alle Grundwerte
(Umsatz, EBIT, Cashflow, Bilanzposten …) mit dem verwendeten XBRL-Feld, Zeitraum und
Einreichungsdatum. Zusätzlich entstehen Dateien `pruefung_AAPL.txt` usw. zum Vergleichen
mit den Geschäftsberichten (10-K / 10-Q auf https://www.sec.gov/edgar/search/).
Andere Titel: im schwarzen Fenster `pruefen.bat MSFT JNJ` eingeben.
Das Prüfprogramm speichert nichts in der Datenbank.

## 6. Schwellenwerte ändern

`config/schwellen.yaml` mit dem Editor (Rechtsklick → Öffnen mit → Editor) öffnen.
Pro Kennzahl gibt es `bei_10`, `bei_5`, `bei_0`. Speichern, im Browser neu laden – fertig.
Oben im Abschnitt `optionen` stehen außerdem: Abzug der Aktienvergütung (an/aus), K.o.-Schwelle
und die Grenzen für das Wachstum in der erwarteten Rendite.
Die Punkte aller Titel werden aus den gespeicherten Rohwerten neu berechnet.
Die Sektor-Zuordnung steht in `config/sic_sektoren.yaml`.

## 7. Aktualisieren und sichern

- Neue Version holen: Doppelklick auf **`aktualisieren.bat`**.
- Sicherung: die Datei `aktien.db` kopieren (z. B. auf einen USB-Stick oder in OneDrive).
  Darin stecken alle Analysen und Einschätzungen.

---

## Wie gerechnet wird (Entscheidungen, die du kennen solltest)

- **Letzte 12 Monate (TTM):** letztes Geschäftsjahr + laufendes Jahr bis zum letzten
  Quartalsbericht – derselbe Zeitraum im Vorjahr. Ersatzweise Summe der letzten 4 Quartale.
  Gibt es nur Jahresberichte (z. B. 20-F), wird das letzte Geschäftsjahr verwendet und markiert.
- **Free Cashflow:** operativer Cashflow – Zahlungen für Sachanlagen (`PaymentsToAcquirePropertyPlantAndEquipment`)
  – **Aktienvergütung** (`ShareBasedCompensation`). Die Aktienvergütung ist ein echter Kostenfaktor,
  wird im operativen Cashflow aber wieder hinzugerechnet. Abschaltbar in `schwellen.yaml`.
  Gilt einheitlich für FCF-Rendite, FCF je Aktie, FCF-Umwandlung, Entschuldungsdauer und erwartete Rendite.
- **FCF-Rendite vs. Historie:** aktuelle FCF-Rendite im Vergleich zum Median der FCF-Rendite an den letzten
  10 Geschäftsjahresenden (FCF ÷ verwässerte Aktien × Kurs am Stichtag). Positiv = günstiger als üblich.
- **DCF-Sicherheitsmarge** (ersetzt die „erwartete Rendite“): drei Szenarien Bear / Base / Bull
  (Gewicht 25 / 50 / 25). Je Szenario: Start-Free-Cashflow (nach Aktienvergütung), 5 Jahre Wachstum,
  danach 5 Jahre gleichmäßig sinkend auf das langfristige Wachstum, Endwert als Durchschnitt aus
  ewigem Wachstum (Gordon) und Branchen-Multiple. Abzinsung = 10-jährige US-Anleihe (live von FRED)
  + Marktrisikoprämie + Branchenzuschlag. Gerechnet wird mit dem FCF nach Zinsen; Schulden stecken
  damit schon in den Zinszahlungen, vorhandenes Nettocash wird addiert.
  Sicherheitsmarge = (gewichteter fairer Wert – Kurs) ÷ fairer Wert.
  Basis-Wachstum = der niedrigere Wert aus Umsatz- und FCF-je-Aktie-Wachstum (geglättet, begrenzt).
  Alle Annahmen und die Branchenwerte stehen in **`config/dcf.yaml`**; Änderungen wirken sofort.
  In der Detailansicht: fairer Wert je Szenario, Annahmen-Tabelle, Empfindlichkeitstabelle,
  Reverse DCF (welches Wachstum im Kurs steckt) und **Wachstum von Hand festlegen** pro Titel.
- **Marktkapitalisierung:** Aktienanzahl vom Deckblatt des letzten Berichts × letzter Schlusskurs.
  Ist die Kurswährung eine andere als die Berichtswährung, werden die betroffenen
  Kennzahlen ausgelassen (keine Umrechnung).
- **Finanzschulden:** zinstragende Schulden (lang- und kurzfristig, inkl. Commercial Paper),
  **ohne** Leasingverbindlichkeiten. **Cash:** Zahlungsmittel + kurzfristige Wertpapiere.
- **EV/EBIT-Historie:** EV je Geschäftsjahresende = Kurs am Stichtag × verwässerte Aktien
  + Finanzschulden – Cash; davon der Median (mind. 5 Jahre). Rohwert = Abweichung des
  aktuellen EV/EBIT in %, negativ = günstiger als üblich.
- **Aktiensplits:** Aktienzahlen werden mit der Split-Historie auf die heutige Basis gebracht.
- **Maximaler Kursrückgang:** Schlusskurse, um Splits bereinigt, ohne Dividenden.
- **Wachstum (Umsatz, FCF je Aktie):** geglättet – vom Durchschnitt dreier Jahre (z. B. 2018–2020) zum
  Durchschnitt der letzten drei (2023–2025). Ein einzelnes Ausnahmejahr am Anfang oder Ende verzerrt
  die Rate so weniger. Bei weniger als 8 Jahren Daten: von Jahr zu Jahr, markiert „ohne Glättung“.
- **ROIC:** NOPAT = EBIT × (1 – effektiver Steuersatz, begrenzt auf 0–35 %, ersatzweise 21 %) ÷
  investiertes Kapital über die **Aktivseite**: Bilanzsumme – Cash – Wertpapiere (kurz- und langfristig)
  – nicht zinstragende kurzfristige Verbindlichkeiten; Durchschnitt aus Jahresanfang und -ende.
  Funktioniert auch bei negativem Eigenkapital. Firmen, die von Kunden vorab bezahlt werden
  (z. B. Apple), kommen dadurch auf sehr hohe Werte – das ist gewollt, es zeigt die Kapitalintensität.
- **Verwässerung:** jährliche Veränderung der verwässerten Aktienanzahl über 5 Jahre.
- **FCF-Umwandlung:** Summe FCF ÷ Summe Nettogewinn über 5 Jahre (stabiler als der
  Durchschnitt einzelner Jahresquoten, die bei kleinen Gewinnen ausreißen).
- **Bruttomarge:** Bruttogewinn ÷ Umsatz; fehlt der Bruttogewinn, Umsatz – Herstellungskosten.
  Standardabweichung der Stichprobe.
- **Beständigkeit:** gibt es weniger als 10 Jahresvergleiche (mind. 5), wird auf 10 hochgerechnet und markiert.
- **Altman Z-Score:** **Originalformel von 1968**, weil deine Schwellen (3,0 / 1,8) genau
  deren Zonen sind. Die Variante für Nicht-Produzenten (Z'') hätte andere Grenzen (2,6 / 1,1).
- **Ausschüttungsrendite:** fehlt ein Posten (z. B. keine Dividende), zählt er als 0 und wird markiert.
- **Entschuldungsdauer** (ersetzt die Current Ratio): Nettoschulden ÷ Free Cashflow der letzten 12 Monate.
  Die Current Ratio bestrafte starke Firmen, die von Kunden früh und von Lieferanten spät bezahlt werden.
- **Sonderfälle:** Nettocash → 10 Punkte (Nettoverschuldung/EBITDA, Entschuldungsdauer);
  Nettoschulden bei negativem FCF → 0 Punkte (Entschuldungsdauer); kein Zinsaufwand ausgewiesen →
  10 Punkte nur ohne Finanzschulden, sonst wird die Zinsdeckung ausgelassen.
- **K.o.-Warnung:** liegt eine eingeschaltete Kategorie unter 3 von 10 Punkten (einstellbar), erscheint
  „⛔ K.o.“. Der Gesamtscore ändert sich dadurch nicht – die Warnung soll verhindern, dass eine
  gravierende Schwäche im Durchschnitt untergeht.
- **Der Sektor** verändert keine Scores. Bei Banken fehlen typischerweise Umlaufvermögen
  und EBIT – diese Kennzahlen werden dann aus den Daten heraus ausgelassen, nicht wegen des Sektors.
- **Gesamtscore:** wird bei jeder Anzeige aus gespeicherten Rohwerten, aktuellen Schwellen
  und aktuellen Gewichten berechnet. Im Verlauf gilt für jede Analyse die Einschätzung,
  die bis zur nächsten Analyse aktuell war.
- **Datenquellen:** FRED (Federal Reserve Bank of St. Louis) für den risikofreien Zins; ist FRED nicht
  erreichbar, nimmt die App den Ersatzwert aus `config/dcf.yaml` und zeigt einen Hinweis.
  SEC EDGAR (companyfacts, submissions), max. 8 Anfragen/Sekunde,
  1 Tag Zwischenspeicher im Ordner `cache/`. Kurse: yfinance (Yahoo Finance) –
  optional Tiingo mit kostenlosem Schlüssel (Seite Einstellungen).

## Für Entwickler

```
start.bat / aktualisieren.bat / pruefen.bat   Windows-Starter
app.py              Streamlit-Navigation
seiten/             die fünf Seiten
analyse.py          Ablauf einer Analyse (holen → rechnen → speichern)
auswertung.py       Scores aus gespeicherten Rohwerten + aktuellen Einstellungen
kern/               reine Berechnung (Punkte, Kennzahlen, Gesamtscore), ohne Oberfläche
daten/              SEC-Client, XBRL-Aufbereitung, Kurse
speicher/db.py      SQLite
config/             schwellen.yaml, sic_sektoren.yaml, settings.toml (lokal)
tests/              pytest:  .venv\Scripts\python -m pytest
```
