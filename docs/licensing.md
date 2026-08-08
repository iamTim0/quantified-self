# Lizenzen

Diese Seite hält fest, unter welcher Lizenz dieses Projekt steht, welche fremde
Software es weitergibt und welche Pflichten daraus folgen. Sie ist eine
Bestandsaufnahme, **keine Rechtsberatung** — die Stellen, an denen es darauf
ankommt, sind unten ausdrücklich als solche markiert.

## Eigener Code: MIT

`LICENSE` im Repository-Wurzelverzeichnis, MIT. Damit das nicht nur dort steht:

- alle dreizehn `pyproject.toml` und die `package.json` des Dashboards deklarieren
  `license = "MIT"`,
- alle dreizehn Images tragen `org.opencontainers.image.licenses=MIT` als
  OCI-Label (gesetzt in `.github/workflows/release.yml`),
- das Deployment-Bundle jedes Releases enthält `LICENSE`.

MIT heißt: jeder darf den Code nehmen, ändern, verkaufen. Auch jemand, der damit
denselben Dienst anbietet. Das ist eine Entscheidung, keine Nachlässigkeit — aber
wer sie später ändern will, sollte wissen, dass jede bereits veröffentlichte
Version für immer MIT bleibt.

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
| PostGIS | GPL-2.0 | Läuft als eigener PostgreSQL-Prozess und wird über SQL erreicht. Das berührt den MIT-Code nicht; GPL kennt keine Netzwerk-Klausel (die hat die AGPL). |
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
3. **Die eigene Lizenz.** MIT erlaubt jedem, denselben Dienst zu betreiben. Wer das
   nicht will, entscheidet sich üblicherweise für AGPL-3.0 (Selbstbetrieb bleibt
   frei, Änderungen eines Wettbewerbers müssen offen sein) oder eine
   source-available Lizenz wie BSL 1.1, die das Anbieten als Dienst befristet
   einschränkt und danach in eine offene Lizenz übergeht. **Diese Wahl ist nur so
   lange kostenlos, wie das Repository privat ist.**
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
