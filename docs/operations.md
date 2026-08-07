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
| `ALLOW_REGISTRATION` | Selbstregistrierung erlauben | nein |
| `ALLOWED_ORIGINS` | CORS-Ursprünge des Gateways | ja |
| `MAP_TILE_HOSTS` | erlaubte Kachel-Hosts in der CSP | nein |

!!! danger "Vor dem ersten produktiven Deployment"
    `JWT_SECRET`, `INTERNAL_SERVICE_SECRET` und `ENCRYPTION_KEY` haben
    Entwicklungs-Defaults, die im Repository stehen. Wer sie kennt, kann Token
    fälschen und gespeicherte Zugangsdaten entschlüsseln. Alle drei müssen gesetzt
    werden:

    ```bash
    python -c "import secrets; print(secrets.token_urlsafe(48))"
    ```

    `INTERNAL_SERVICE_SECRET` muss auf Core **und** allen Importern identisch sein.
    Ein Wechsel von `ENCRYPTION_KEY` macht bereits gespeicherte Connector-Zugangsdaten
    unlesbar; diese müssen dann neu hinterlegt werden.

## Deployment

`docker-compose.coolify.yml` beschreibt den Produktions-Stack: Traefik, Gateway,
Core, Dashboard, Dokumentation und die acht Importer.

```bash
docker compose -f docker-compose.coolify.yml up -d --build
docker compose -f docker-compose.coolify.yml run --rm core alembic upgrade head
```

Migrationen laufen bewusst als eigener Schritt und nicht beim Start eines Dienstes:
mehrere gleichzeitig startende Repliken würden sonst gegeneinander migrieren.

### Netzwerkgrenzen

Nach außen gehören nur Traefik und dadurch Gateway, Dashboard und Docs. **Core
darf nicht öffentlich erreichbar sein** — es liefert über
`/api/v1/internal/*` entschlüsselte Connector-Zugangsdaten aus. Core authentifiziert
zwar inzwischen selbst, aber die Portfreigabe bleibt unnötige Angriffsfläche.

Die Importer für Apple Health (`:8005`) und Streak (`:8006`) müssen erreichbar sein,
weil externe Geräte an sie senden.

## Monitoring

- **Healthchecks**: jeder Dienst bietet `GET /health`; die Docs zusätzlich `/healthz`.
- **Korrelation**: jede Zeile trägt `[req_id=…]`. Ein Import lässt sich damit von der
  Auslösung bis zum geschriebenen Datenpunkt verfolgen.
- **Importhistorie**: `GET /api/v1/data/sources/{type}/sync-runs` zeigt Fenster,
  Modus, Status und Zähler je Lauf — die verlässlichste Quelle für „warum fehlen
  Daten".

```bash
task logs -- --service qs-core --level ERROR
docker compose -f docker-compose.coolify.yml logs -f core
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
- Der Sperrmechanismus gegen parallele Syncs (`active_syncs`) ist **prozesslokal**.
  Bei mehreren Repliken eines Importers verhindert er keine Doppelläufe mehr; die
  Idempotenz fängt das ab, aber es entsteht unnötige Last.
