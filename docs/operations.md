# Betrieb, Deployment und Monitoring

## Lokale Entwicklung

```bash
task dev:up            # Postgres, NATS, Traefik, Dashboard, Docs
task db:migrate        # Alembic auf head
task dev:local         # Backends lokal statt im Container
task docs:serve        # Dokumentation auf :8003
```

Ohne Postgres auf `:5433` schlagen die Integrationstests fehl — das ist erwartet,
kein Defekt.

## Tests

```bash
task test:all          # Specs, Core, Gateway, E2E, Importer
task test:core         # nur Core (braucht Postgres)
task test:importers    # alle acht Importer
task lint:all          # Ruff, ESLint, tsc
task docs:build        # MkDocs --strict
```

## Erforderliche Konfiguration

| Variable | Zweck | Produktionspflicht |
| --- | --- | --- |
| `DATABASE_URL` | PostgreSQL-Verbindung | ja |
| `NATS_URL` | Broker | ja |
| `JWT_SECRET` | Signatur der Nutzer-Token | **ja — Default ist unsicher** |
| `INTERNAL_SERVICE_SECRET` | Signatur/Geheimnis interner Dienstaufrufe | **ja** |
| `ENCRYPTION_KEY` | Fernet-Schlüssel für Connector-Zugangsdaten | **ja** |
| `ACCESS_TOKEN_TTL_MINUTES` | Laufzeit Zugriffstoken (Standard 720) | nein |
| `REFRESH_TOKEN_TTL_DAYS` | Laufzeit Erneuerungstoken (Standard 30) | nein |
| `ALLOW_REGISTRATION` | Selbstregistrierung erlauben. **Standard `false`** — das erste Konto legt `python -m core.create_owner` an | nein |
| `PUBLIC_HOST` | Hostname, unter dem Traefik ausliefert. Steht bewusst nirgends im Repository | ja |
| `ALLOWED_ORIGINS` | CORS-Ursprünge des Gateways | ja |
| `MAP_TILE_HOSTS` | erlaubte Kachel-Hosts in der CSP | nein |

!!! danger "Ohne diese drei Werte startet der Produktions-Stack nicht mehr"
    `JWT_SECRET`, `INTERNAL_SERVICE_SECRET` und `ENCRYPTION_KEY` haben
    Entwicklungs-Defaults, die im Repository stehen. Wer sie kennt, kann Token
    fälschen und gespeicherte Zugangsdaten entschlüsseln.

    Bis vor Kurzem war das eine Bitte: das Produktions-Compose enthielt
    `${JWT_SECRET:-dev-secret-key-quantified-self-2026}`, ein Deployment ohne
    gesetzte Variable lief also mit dem öffentlichen Wert — und sagte nichts.
    `docker-compose.prod.yml` verwendet `${VAR:?…}`; fehlt eine Variable, bricht
    `docker compose` ab, bevor ein Container startet. Zusätzlich verweigern Core
    und Gateway den Start, wenn `ENVIRONMENT` produktiv ist und ein Wert einem
    veröffentlichten Default entspricht.

    ```bash
    python -c "import secrets; print(secrets.token_urlsafe(48))"
    ```

    `INTERNAL_SERVICE_SECRET` muss auf Core **und** allen Importern identisch sein.

### `ENCRYPTION_KEY` wechseln

Dieser Schlüssel ist der einzige, der sich nicht einfach ersetzen lässt: er
entschlüsselt bereits gespeicherte Connector-Zugangsdaten und OIDC-Client-Secrets.
Wird er ohne Vorbereitung geändert, sind alle hinterlegten Tokens dauerhaft
unlesbar — die Importer laufen leer und es gibt nichts, worauf man zurückfallen
könnte.

Deshalb zuerst umschlüsseln, dann umstellen:

```bash
# 1. Probelauf. Zeigt, was passieren würde, und schreibt nichts.
docker compose -f docker-compose.prod.yml run --rm core \
  python -m core.rotate_encryption_key --old "$ALT" --new "$NEU" --dry-run

# 2. Umschlüsseln. Eine Transaktion; ein Abbruch lässt alles auf dem alten Schlüssel.
docker compose -f docker-compose.prod.yml run --rm core \
  python -m core.rotate_encryption_key --old "$ALT" --new "$NEU"

# 3. Erst jetzt ENCRYPTION_KEY auf den neuen Wert setzen und Core neu starten.
```

Das Werkzeug bricht ab, sobald ein Wert sich mit **keinem** der beiden Schlüssel
entschlüsseln lässt, und schreibt dann gar nichts. Eine Datenbank, die halb auf
dem alten und halb auf dem neuen Schlüssel liegt, wäre der teure Fehler, denn
nichts hielte fest, welche Zeile auf welchem liegt. Werte, die bereits auf dem
neuen Schlüssel liegen, bleiben unangetastet — ein zweiter Lauf nach einem
Abbruch ist also gefahrlos.

!!! tip "Wenn der Probelauf »UNREADABLE« meldet"
    Dann liegt mindestens ein Wert auf einem dritten Schlüssel. Das passiert, wenn
    dieselbe Datenbank zwischenzeitlich mit unterschiedlicher Konfiguration
    betrieben wurde. Diese Zugangsdaten sind nicht wiederherstellbar; sie müssen im
    Dashboard neu hinterlegt werden. Danach läuft die Umschlüsselung durch.

### Das erste Konto anlegen

`ALLOW_REGISTRATION` steht standardmäßig auf `false`. Eine persönliche
Analyseplattform, die für jeden offen ist, sollte eine Entscheidung sein und
nicht das, was passiert, wenn man nichts konfiguriert. Damit gibt es allerdings
zunächst keinen Weg hinein — dafür ist dieser Befehl da:

```bash
docker compose -f docker-compose.prod.yml run --rm core \
  python -m core.create_owner --email du@example.com --workspace "Meine Daten"
```

Das Passwort wird abgefragt, nicht als Argument übergeben: Kommandozeilen landen
in der Shell-History, in `ps` und in CI-Logs. Für automatisierte Einrichtung geht
`QS_OWNER_PASSWORD` als Umgebungsvariable. Mindestlänge sind 12 Zeichen — dieses
Konto ist der gesamte Zugang, und wer es anlegt, kann frei wählen.

Ein zweiter Aufruf mit derselben Adresse **überschreibt nichts**, sondern bricht
ab. Ein Passwort zurückzusetzen ist `--reset-password` und damit eine bewusste
Anweisung; das beendet zugleich alle bestehenden Sitzungen des Kontos.

Bewusst ein Befehl und kein Startschritt: Regel 9 verbietet Diensten das Anlegen
von Daten beim Hochfahren, und warum, steht in der Geschichte dieses Repositories
— `infra/db/init.sql` legte früher ein Konto mit einem mitgeliefertem
Passwort-Hash an, sodass jeder Klon dieselben Zugangsdaten für dieselbe Adresse
enthielt.

Wer Selbstregistrierung tatsächlich will, setzt `ALLOW_REGISTRATION=true` — und
sollte wissen, dass die Anwendung dann für jeden offensteht, der die Adresse
kennt.

## Deployment

`docker-compose.prod.yml` beschreibt den Produktions-Stack: Traefik, Gateway, Core,
Analyse, Dashboard, Dokumentation und die acht Importer. Es **baut nichts**, sondern
zieht die Images, die der Release-Workflow veröffentlicht hat — ein Deployment ist
ein Download und ein Neustart.

Die vollständige Anleitung — Release erzeugen, Erstinstallation, Aktualisieren,
Zurückrollen, Variablen dieses Stacks — steht unter
[Release & Deployment](deployment.md). Kurz:

```bash
export PUBLIC_HOST=deine-domain.example
export JWT_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
export INTERNAL_SERVICE_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
export ENCRYPTION_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
export ALLOWED_ORIGINS=https://$PUBLIC_HOST
export QS_VERSION=1.0.0        # welches Release laufen soll

docker compose -f docker-compose.prod.yml config >/dev/null   # nennt fehlende Variablen
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml run --rm core alembic upgrade head
docker compose -f docker-compose.prod.yml run --rm core \
  python -m core.create_owner --email du@example.com --workspace "Meine Daten"
```

Migrationen laufen bewusst als eigener Schritt und nicht beim Start eines
Dienstes: mehrere gleichzeitig startende Repliken würden sonst gegeneinander
migrieren. Selbstregistrierung ist aus, deshalb der letzte Befehl — siehe
[Das erste Konto anlegen](#das-erste-konto-anlegen).

Stehen schon Nutzdaten in der Datenbank, ist `ENCRYPTION_KEY` **nicht** frei
wählbar — dann zuerst [umschlüsseln](#encryption_key-wechseln).

### Testen

`tools/smoke_deployment.sh` prüft ein Deployment von außen — erreichbar,
verschlossen, und was es selbst über seine Konfiguration sagt:

```bash
bash tools/smoke_deployment.sh https://$PUBLIC_HOST

# Mit Zugangsdaten zusätzlich Anmeldung, ein tenant-bezogener Lesezugriff
# und die Selbstauskunft:
OWNER_EMAIL=du@example.com OWNER_PASSWORD='…' \
  bash tools/smoke_deployment.sh https://$PUBLIC_HOST
```

Geprüft wird:

| Prüfung | Erwartung |
| --- | --- |
| `/health` | `200` |
| `/` | `200` — Dashboard |
| `/docs/` | die Dokumentation, am Seiteninhalt erkannt und nicht nur am Statuscode |
| `POST /api/v1/auth/signup` | **`403`** — sonst steht die Anwendung jedem offen, der die Adresse kennt |
| `/api/v1/data/metrics` ohne Sitzung | `401` |
| `/api/v1/internal/…` | **nicht** `200` — dort liegen entschlüsselte Connector-Zugangsdaten |
| Anmeldung + Lesezugriff | `200` |
| `/api/v1/data/system/warnings` | leer |

Der letzte Punkt ist der aussagekräftigste: er fragt die Anwendung, was sie
selbst an ihrer Konfiguration auszusetzen hat. Ein korrekt eingerichtetes
Produktions-Deployment meldet dort nichts.

!!! note "Über `http://` sind zwei Ergebnisse erwartbar"
    Secure-Cookies können über unverschlüsseltes HTTP nicht übertragen werden. Ein
    Deployment, das nur per `http` erreichbar ist, braucht daher
    `COOKIE_SECURE=false` — und meldet dann `cookies_not_secure`. Das Skript
    bewertet die Selbstauskunft deshalb nur bei `https`-Adressen und gibt sie
    ansonsten bloß aus.

    `/docs/` schlägt außerdem fehl, wenn Traefik und der Docs-Container nicht
    laufen: dann antwortet dort das Dashboard.

### Netzwerkgrenzen

Nach außen gehören nur Traefik und dadurch Gateway, Dashboard und Docs. **Core
darf nicht öffentlich erreichbar sein** — es liefert über
`/api/v1/internal/*` entschlüsselte Connector-Zugangsdaten aus. Core authentifiziert
zwar inzwischen selbst, aber die Portfreigabe bleibt unnötige Angriffsfläche.

Seit `docker-compose.prod.yml` ist das keine Bitte mehr, sondern der Zustand:
**Core veröffentlicht keine Host-Ports.** Das alte Produktions-Compose gab `8001`
und `50051` frei, obwohl Traefik sie nie geroutet hat. Innerhalb des Compose-Netzes
ist Core unverändert unter `core:8001` und `core:50051` erreichbar.

Ebenso hängt das Traefik-Dashboard jetzt auf `127.0.0.1` statt auf allen
Schnittstellen — es läuft mit `--api.insecure=true` und war damit auf einem
öffentlichen Host eine unauthentifizierte Admin-UI. Zugriff über einen SSH-Tunnel:
`ssh -L 8081:127.0.0.1:8081 user@host`.

Die Importer für Apple Health (`:8005`) und Streak (`:8006`) müssen erreichbar sein,
weil externe Geräte an sie senden.

## Selbstauskunft im Dashboard

Die Punkte aus diesem Kapitel muss man nicht hier nachlesen, um sie zu bemerken:
Core meldet sie über `GET /api/v1/data/system/warnings`, und das Dashboard zeigt
sie Inhabern und Administratoren als Banner über dem Inhalt — auf jedem Tab, mit
dem jeweiligen Befehl zum Kopieren.

Gemeldet werden veröffentlichte Standardwerte für `JWT_SECRET`,
`ENCRYPTION_KEY` und `INTERNAL_SERVICE_SECRET`, offene Selbstregistrierung,
fehlendes `Secure`-Flag auf den Cookies, und ein Passwort, dessen Hash in einer
veröffentlichten Quelle stand. Details und die Begründung, wer was sehen darf,
unter [Warnungen im Dashboard](features/authentication.md#warnungen-im-dashboard).

Ein produktives Deployment sollte hier nichts anzeigen. Tut es das doch, ist
mindestens einer der Werte aus
[Erforderliche Konfiguration](#erforderliche-konfiguration) nicht gesetzt.

## Monitoring

- **Healthchecks**: jeder Dienst bietet `GET /health`; die Docs zusätzlich `/healthz`.
- **Korrelation**: jede Zeile trägt `[req_id=…]`. Ein Import lässt sich damit von der
  Auslösung bis zum geschriebenen Datenpunkt verfolgen.
- **Importhistorie**: `GET /api/v1/data/sources/{type}/sync-runs` zeigt Fenster,
  Modus, Status und Zähler je Lauf — die verlässlichste Quelle für „warum fehlen
  Daten".

```bash
task logs -- --service qs-core --level ERROR
docker compose -f docker-compose.prod.yml logs -f core
```

## Datensicherung

Gesichert werden muss ausschließlich PostgreSQL — alle anderen Dienste sind
zustandslos.

```bash
docker compose exec postgres pg_dump -U qs_dev quantified_self | gzip > backup.sql.gz
```

Zusätzlich zu sichern sind `ENCRYPTION_KEY` und `JWT_SECRET`: ohne den
Verschlüsselungsschlüssel ist ein Backup der Connector-Zugangsdaten wertlos.

## Skalierung

- Importer sind zustandslos und laufen in NATS-Queue-Groups; mehrere Repliken
  teilen die Last automatisch.
- Cores Ingest-Consumer nutzt ebenfalls eine Queue-Group.
- Doppelläufe verhindert **Core**, nicht der Importer: ein Connector mit bereits
  eingereihtem oder laufendem `SyncRun` wird nicht erneut eingeplant. Die
  `active_syncs`-Menge in den Importern ist nur noch ein lokaler Puffer gegen eine
  erneut zugestellte Nachricht — sie war nie eine verteilte Sperre, und bei
  mehreren Repliken hätte sie nichts verhindert.
- Der Scheduler ist über einen transaktionsgebundenen Postgres-Advisory-Lock
  single-flight. Mehrere Core-Repliken sind damit unbedenklich: pro Tick plant
  genau eine. Stirbt sie, gibt die Verbindung den Lock frei.
- Der Analysedienst ist zustandslos und hält keine Datenbankverbindung; er
  skaliert unabhängig von Core.
