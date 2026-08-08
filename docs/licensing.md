# Lizenzen

Diese Seite hält fest, unter welcher Lizenz dieses Projekt steht, welche fremde
Software es weitergibt und welche Pflichten daraus folgen. Sie ist eine
Bestandsaufnahme, **keine Rechtsberatung** — die Stellen, an denen es darauf
ankommt, sind unten ausdrücklich als solche markiert.

## Eigener Code: AGPL-3.0

`LICENSE` im Repository-Wurzelverzeichnis: GNU Affero General Public License,
Version 3, im Wortlaut der FSF, mit einer Copyright-Zeile davor. Damit das nicht
nur dort steht:

- alle dreizehn `pyproject.toml` und die `package.json` des Dashboards deklarieren
  `license = "AGPL-3.0-only"`,
- alle dreizehn Images tragen `org.opencontainers.image.licenses=AGPL-3.0-only`
  als OCI-Label,
- das Deployment-Bundle jedes Releases enthält `LICENSE`.

Vorher war das Projekt MIT lizenziert. Der Wechsel war möglich, weil zu diesem
Zeitpunkt **niemand** eine Kopie erhalten hatte: das Repository war privat, die
GHCR-Packages waren privat, und das eine Release `v0.1.0` wurde gelöscht. MIT ist
eine Rechteeinräumung an Empfänger — ohne Empfänger gibt es nichts, was bindet. Die
Commit-Historie kennt genau einen Autor, also war auch keine Zustimmung Dritter
nötig.

!!! warning "§13 ist eine Pflicht für den Betreiber, nicht nur für Weitergeber"
    Wer die Software über ein Netzwerk benutzbar macht, muss den Nutzern den
    **Corresponding Source der laufenden Version** anbieten. Ein Link auf den
    Default-Branch genügt dafür nicht — deployter Stand und Branch-Spitze laufen
    beim nächsten Merge auseinander.

    Deshalb bekommt das Dashboard-Image die Version und den Commit als Build-Argument
    (`SOURCE_VERSION`, `SOURCE_COMMIT`, gesetzt vom Release-Workflow), und der Footer
    verlinkt genau diesen Stand. Ein lokaler Build ohne diese Argumente verlinkt das
    Repository. Wer das Image selbst baut und öffentlich betreibt, muss die
    Argumente setzen oder den Link anders korrekt füllen.

Die AGPL erlaubt Selbstbetrieb und Veränderung uneingeschränkt. Wer den Dienst
für andere betreibt und den Code dafür ändert, muss diese Änderungen offenlegen.
Für die Abhängigkeiten ist das unkritisch: alle sind MIT, BSD-2-Clause, ISC oder
Apache-2.0, und Apache-2.0 ist mit GPLv3 vereinbar (mit v2 wäre es das nicht).

## Weitergegebene fremde Software

Ein Container-Image ist eine Kopie im Sinne der Lizenzen. MIT, BSD-2-Clause und
ISC verlangen alle, dass ihr Copyright-Hinweis eine Kopie begleitet.

**Python-Images** (Core, Analyse, Gateway, acht Importer): die Abhängigkeiten
werden ins venv installiert, das die Dockerfiles als Ganzes ins Image kopieren —
mit den Lizenzdateien in den `*.dist-info`-Verzeichnissen. Cores venv enthält 42.

**Dashboard-Image**: `apps/dashboard/THIRD-PARTY-NOTICES.txt`, erzeugt von
`scripts/generate-notices.ts` aus dem Produktions-Abhängigkeitsbaum (22 Pakete),
plus den beiden selbst gehosteten Webfonts. Die Datei wird im Builder neu erzeugt
und ins Runtime-Image kopiert; die CI prüft mit `bun run notices --check`, dass die
committete Fassung zum Abhängigkeitsbaum passt.

!!! note "Warum das eine eigene Datei braucht"
    Früher lieferte das Image die vollständigen `node_modules` aus — und damit
    zufällig 271 Lizenzdateien mit. Die Umstellung auf Nexts Standalone-Output hat
    das Image von 636 MB auf 155 MB verkleinert, weil nur noch der tatsächlich
    erreichte JavaScript-Code eingespurt wird — Lizenzdateien gehören nicht dazu.
    Die Pflicht blieb, der Hinweis verschwand. Deshalb jetzt absichtlich statt
    versehentlich.

**Schriften**: `next/font/google` lädt Outfit und JetBrains Mono beim Build
herunter und legt elf `.woff2` ins Bundle — das Dashboard hostet sie also selbst
und gibt sie weiter. Beide stehen unter OFL-1.1, die Copyright-Hinweis und
Lizenztext bei der Weitergabe verlangt. Die Texte liegen unter
`apps/dashboard/licenses/` und stammen unverändert aus den Upstream-Projekten.

**Kartenkacheln**: Die Attribution für OpenStreetMap und CARTO ist im
`TileLayer` gesetzt und wird in der Karte gerendert — das ist die ODbL-Pflicht.

## Komponenten mit Bedingungen, die man kennen sollte

| Komponente | Lizenz | Was das bedeutet |
| --- | --- | --- |
| TimescaleDB | Apache-2 **und** TSL | Genutzt wird ausschließlich `create_hypertable` — das liegt im Apache-2-Teil. Die TSL-Features (Compression, Continuous Aggregates, Retention Policies) sind derzeit **nicht** im Einsatz. |
| PostGIS | GPL-2.0 | Läuft als eigener PostgreSQL-Prozess und wird über SQL erreicht — getrennte Programme, keine Verlinkung. Mit AGPL-3.0 ist GPL-2.0-only ohnehin nur so vereinbar, nicht im selben Prozess. |
| NATS, cloudflared, gRPC, asyncpg | Apache-2.0 | Verlangen die Weitergabe vorhandener `NOTICE`-Dateien — erfüllt, weil die Images die Pakete samt ihrer Lizenzdateien enthalten. |
| Traefik, Material for MkDocs, Bun, Next.js, React | MIT | Hinweis muss mitreisen; siehe oben. |
| Leaflet | BSD-2-Clause | Wie MIT, mit ausdrücklicher Klausel — steht in `THIRD-PARTY-NOTICES.txt`. |
| Yazio-API | keine Lizenz, private API | Siehe unten. |

## Wenn daraus ein Dienst für andere wird

Für den Eigenbetrieb ändert sich nichts. Wer die Plattform **anderen als Dienst
anbietet**, sollte diese sechs Punkte vorher geklärt haben. Die ersten beiden sind
die praktisch riskantesten, und keiner davon ist eine Lizenzfrage im engeren Sinn.

1. **Yazio.** Der Importer spricht `yzapi.yazio.com` mit den OAuth-Client-Daten der
   Yazio-App — sie stecken in `services/core/src/core/config.py`, weil sie in deren
   App ausgeliefert werden. Für den eigenen Datenexport ist das eine Grauzone, die
   in der Praxis niemanden stört. Für ein bezahltes Produkt ist es eine andere
   Unterhaltung: fremde App-Zugangsdaten gegen eine nicht dokumentierte API sind
   der wahrscheinlichste Grund, abgeschaltet zu werden. **Hier gehört ein Anwalt
   hin, oder eine offizielle Freigabe.**
2. **Gesundheitsdaten.** Das sind besondere Kategorien nach Art. 9 DSGVO. Für
   fremde Nutzer heißt das mindestens: ausdrückliche Einwilligung, sehr
   wahrscheinlich eine Datenschutz-Folgenabschätzung nach Art. 35, Verträge zur
   Auftragsverarbeitung mit jedem Unterauftragnehmer, ein Verarbeitungsverzeichnis
   und belastbare Auskunfts-, Export- und Löschwege. Tenant-Trennung und
   verschlüsselte Connector-Zugangsdaten sind die halbe Miete, die andere Hälfte
   ist Papier. **Auch das ist ein Anwaltsthema, nicht ein Code-Thema.**
3. **Die eigene Lizenz** ist entschieden: AGPL-3.0. Selbstbetrieb bleibt für jeden
   frei, aber wer den Dienst betreibt und den Code dafür ändert, muss die Änderungen
   offenlegen. Der Preis dafür ist §13, siehe oben — die Pflicht trifft auch den
   eigenen Betrieb.
4. **WHOOP.** Offizielle Developer-API (`api.prod.whoop.com/developer`) — die
   Nutzung läuft unter deren Developer-Terms, kommerzielle Nutzung braucht dort
   üblicherweise eine Freigabe.
5. **Kartenkacheln.** `tile.openstreetmap.org` ist nach OSMs Tile Usage Policy
   nicht für kommerzielle oder verkehrsstarke Nutzung gedacht. Das ist eine
   Konfigurationsfrage, kein Umbau: Provider über `NEXT_PUBLIC_MAP_TILE_PROVIDER`
   wechseln und `MAP_TILE_HOSTS` in der CSP anpassen.
6. **Wetter.** Der Importer bekommt seinen Host aus der Connector-Konfiguration,
   das Projekt schreibt keinen Anbieter fest. Wer Open-Meteo nutzt: der freie Zugang
   ist für nicht-kommerzielle Nutzung gedacht, kommerziell gibt es einen Tarif.

## Prüfen

```bash
task check:private                        # keine personenbezogenen Daten im Repo
bun run --cwd apps/dashboard notices      # Hinweise neu erzeugen
bun run --cwd apps/dashboard notices --check   # läuft auch in der CI
```
