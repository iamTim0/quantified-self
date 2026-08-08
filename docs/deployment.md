# Release und Deployment

Diese Seite beschreibt beide Hälften eines Deployments: wie aus einem Commit auf
`main` ein veröffentlichtes Release mit Container-Images wird, und wie dieses
Release auf einem Server läuft. Für den laufenden Betrieb danach — Pflichtvariablen,
Schlüsselwechsel, Backup, Monitoring — siehe [Betrieb](operations.md).

## Warum überhaupt Images

Vorher beschrieb `docker-compose.coolify.yml` den Produktions-Stack und baute alle
dreizehn Images **auf dem Zielserver**. Das hatte drei Konsequenzen, die im Alltag
wehtun:

- Ein Deployment brauchte das Repository, eine Toolchain und mehrere Minuten CPU
  auf einer Maschine, die eigentlich nur laufen lassen soll.
- Was in Produktion lief, war genau einmal gebaut worden, von niemandem, ohne
  Nachweis aus welchem Commit.
- Ein Rollback bedeutete „hoffentlich baut der alte Stand noch genauso".

Jetzt baut `.github/workflows/release.yml` die Images einmal, signiert ihre
Herkunft und lädt sie in die GitHub Container Registry (GHCR). Ein Deployment ist damit ein Download und ein Neustart, und
`docker-compose.prod.yml` enthält keinen einzigen `build:`-Eintrag mehr.

## Ein Release erzeugen

Der Workflow startet **ausschließlich manuell**. Neben `workflow_dispatch` steht
kein `push:`- und kein `schedule:`-Trigger — ein Merge nach `main` veröffentlicht
also nichts. Das ist Absicht: ein Image zu veröffentlichen, das ein Deployment
zieht, und dabei `latest` zu verschieben, ist eine Entscheidung.

Der vorgesehene Ablauf:

1. Änderung nach `main` mergen.
2. Warten, bis die CI für diesen Commit grün ist.
3. **Actions → Release → Run workflow**, Branch `main`, Version eintragen.

Schritt 2 muss man nicht selbst kontrollieren. Der `guard`-Job fragt die CI-Runs
für **genau diesen Commit-SHA** ab — nicht „den letzten Lauf auf main", was sich
unterscheidet, sobald zwei Commits kurz hintereinander landen — und bricht ab,
wenn dort kein erfolgreicher Lauf steht.

### Eingaben

| Eingabe | Bedeutung |
| --- | --- |
| `version` | Semantische Version ohne führendes `v`, z. B. `1.0.0` oder `1.1.0-rc.1`. Ein vorhandenes `v<version>`-Tag lässt den Lauf abbrechen. |
| `platforms` | `linux/amd64` (Standard) oder `linux/amd64,linux/arm64`. arm64 wird emuliert und verdreifacht die Laufzeit etwa — das Next.js-Build unter QEMU ist der Grund. |
| `tag_latest` | Verschiebt zusätzlich `:latest`. Bei einem Pre-Release wird es ignoriert. |
| `prerelease` | Markiert das GitHub-Release als Vorabversion. Eine Version mit Suffix (`-rc.1`) setzt das ohnehin selbst. |
| `dry_run` | Baut alle Images, pusht nichts und erzeugt kein Release. Der Weg, einen Release-Lauf zu testen. |
| `allow_failed_ci` | Veröffentlicht trotz roter oder fehlender CI. Bewusste Ausnahme, keine Abkürzung. |

### Was der Lauf produziert

Pro Image bis zu vier Tags:

```text
ghcr.io/iamtim0/quantified-self/core:1.0.0        # die Version
ghcr.io/iamtim0/quantified-self/core:sha-a1b2c3d  # der Commit
ghcr.io/iamtim0/quantified-self/core:1.0          # wandernder Minor-Tag
ghcr.io/iamtim0/quantified-self/core:latest       # wandernd, nie bei Pre-Releases
```

`sha-…` ist der Tag, der ein veröffentlichtes Image ohne Vertrauen in einen
verschiebbaren Namen auf einen Quellstand zurückführt.

Die beiden **wandernden** Tags setzt ein eigener Job (`promote`), erst nachdem
alle dreizehn Images gebaut sind. Der Grund ist `fail-fast: false`: schlägt das
zwölfte Image fehl, sind die anderen zwölf längst gepusht. Würden sie `latest`
gleich mitziehen, zeigte `latest` für zwölf Images auf die neue Version und für
das dreizehnte auf die alte — ein Stack, den niemand zusammengestellt und niemand
getestet hat. Zusätzlich wandern sie nur bei einem Lauf vom Default-Branch: ein
Lauf aus einem nicht gemergten Branch veröffentlicht `1.0.0` und `sha-…`, bewegt
aber nichts, worauf ein Deployment zeigt.

Für jedes Image schreibt der Workflow außerdem eine signierte Build-Provenance in
die Registry (`actions/attest-build-provenance`), prüfbar mit:

```bash
gh attestation verify --owner iamTim0 \
  oci://ghcr.io/iamtim0/quantified-self/core:1.0.0
```

Dazu entsteht ein GitHub-Release mit dem Tag `v<version>`, dem Changelog und einem
Anhang `quantified-self-<version>-deploy.tar.gz`. Dieses Bundle enthält genau das,
was ein Server braucht — `docker-compose.prod.yml`, `infra/db/init.sql`, eine
vorbereitete `.env` mit gepinnter Version und eine Kurzanleitung. Kein Quellcode,
kein Git, keine Toolchain.

Die Release-Notes listen außerdem den Digest jedes Images. Wo es reproduzierbar
sein muss, pinnt man den Digest statt des Tags.

### Einmalig: Sichtbarkeit der Packages

**GHCR-Packages sind nach dem ersten Push privat, auch in einem öffentlichen
Repository.** Die Sichtbarkeit erbt nicht. Solange sie privat sind, scheitert
`docker compose pull` für jeden außer dem Besitzer mit `denied`.

Einmal pro Package unter `github.com/users/<owner>/packages` → *Package settings* →
*Change visibility* → *Public*. Danach nie wieder.

Weitere Secrets braucht der Workflow nicht: das automatische `GITHUB_TOKEN` darf
in diesem Repository Packages und Releases schreiben.

### Vor dem Release lokal prüfen

Die dreizehn Images werden nirgends sonst zusammen gebaut, und ein Dockerfile kann
verrotten, ohne dass ein Test es merkt — genau das war beim Dashboard passiert: es
hatte zwei Lockfiles, die CI installierte aus `package-lock.json`, das Dockerfile
aus einem veralteten `pnpm-lock.yaml`. Inzwischen gibt es nur `bun.lock` und ein
Werkzeug, das es überall liest. Trotzdem gilt:

```bash
task images:build                    # alle dreizehn, wie im Release-Workflow
task images:build -- core dashboard  # nur bestimmte
```

Die Liste der Images steht einmal in `tools/build_images.py`; der Workflow liest
seine Build-Matrix daraus. Ein neuer Importer, der dort fehlt,
lässt die CI fehlschlagen, statt einfach nie veröffentlicht zu werden.

## Deployment

### Voraussetzungen

- Ein Host mit Docker und Docker Compose v2. Nichts weiter — kein Python, kein
  Node, kein Checkout.
- Ein DNS-Name, der auf den Host zeigt, in `PUBLIC_HOST`.
- TLS davor: ein Reverse Proxy, die Ingress von Coolify, oder das
  `cloudflared`-Profil dieses Stacks.

### Erstinstallation

```bash
# 1. Bundle des Releases holen und auspacken. Die Versions-URL, nicht
#    /releases/latest/download/ — der Alias zeigt auf das neueste Release und
#    sucht dort genau diesen Dateinamen, läuft also ins 404, sobald etwas
#    Neueres erscheint.
curl -fsSL https://github.com/iamTim0/quantified-self/releases/download/v1.0.0/quantified-self-1.0.0-deploy.tar.gz | tar -xz
cd quantified-self-1.0.0

# 2. Konfiguration ausfüllen: PUBLIC_HOST, die drei Secrets und
#    POSTGRES_PASSWORD. Letzteres ist nur jetzt wählbar — PostgreSQL setzt es
#    beim Initialisieren des leeren Volumes in Schritt 4.
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # je Secret einmal
$EDITOR .env

# 3. Prüfen, bevor etwas startet. Nennt jede fehlende Variable beim Namen.
docker compose -f docker-compose.prod.yml config >/dev/null

# 4. Images ziehen und starten.
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d

# 5. Migrieren.
docker compose -f docker-compose.prod.yml run --rm core alembic upgrade head

# 6. Erstes Konto anlegen — es gibt keines, und Selbstregistrierung ist zu.
docker compose -f docker-compose.prod.yml run --rm core \
  python -m core.create_owner --email du@example.com --workspace "Meine Daten"
```

Aus einem Checkout heraus geht dasselbe kürzer:

```bash
task prod:config    # Schritt 3
task prod:up        # Schritte 4 und 5
task prod:owner -- --email du@example.com --workspace "Meine Daten"
```

Schritt 5 ist bewusst ein eigener Schritt und kein Container-Start: mehrere
gleichzeitig startende Repliken würden sonst gegeneinander migrieren.

!!! danger "Ohne die drei Secrets startet nichts"
    `JWT_SECRET`, `INTERNAL_SERVICE_SECRET` und `ENCRYPTION_KEY` haben
    Entwicklungs-Defaults, die in diesem Repository stehen. `docker-compose.prod.yml`
    verwendet `${VAR:?…}`, bricht also ab, bevor ein Container startet. Details und
    die Reihenfolge-Falle bei `ENCRYPTION_KEY` unter
    [Erforderliche Konfiguration](operations.md#erforderliche-konfiguration).

### Variablen dieses Stacks

Über die Pflichtvariablen aus [Betrieb](operations.md#erforderliche-konfiguration)
hinaus steuern diese das Deployment selbst:

| Variable | Standard | Zweck |
| --- | --- | --- |
| `QS_VERSION` | `latest` | Welche Release-Images gezogen werden. Für alles, was rollbackfähig sein soll, eine echte Version eintragen. |
| `QS_IMAGE_PREFIX` | `ghcr.io/iamtim0/quantified-self` | Registry-Pfad. Für einen Fork oder eine Spiegelung anpassen. |
| `QS_HTTP_PORT` | `80` | Host-Port für Traefik — der einzige, der öffentlich sein muss. |
| `QS_GATEWAY_PORT` | `8000` | Direktzugang zum Gateway an Traefik vorbei. Kann entfallen. |
| `QS_APPLE_HEALTH_PORT` | `8005` | Ziel der iPhone-Automation. |
| `QS_STREAK_PORT` | `8006` | Eingehende Streak-Daten (zusätzlich als `/ingest` über Traefik geroutet). |
| `QS_TRAEFIK_DASHBOARD_PORT` | `8081` | Traefik-Dashboard, **nur auf Loopback** gebunden. |
| `POSTGRES_PASSWORD` | `qs_dev_password` | Nur im Compose-Netz erreichbar. Siehe Hinweis unten. |
| `ALLOWED_ORIGINS` | `https://${PUBLIC_HOST},http://${PUBLIC_HOST}` | CORS-Ursprünge des Gateways. Der Standard ist die eigene Origin in beiden Schemata — **nicht** `*`: das Gateway läuft mit `allow_credentials=True`, und ein Wildcard lässt Starlette jede fragende Origin zurückspiegeln. Beide Schemata, weil vor dem Stack ein Proxy oder Tunnel TLS beenden kann und `QS_HTTP_PORT` bewusst http ist. |
| `TUNNEL_TOKEN` | leer | Nur mit `--profile tunnel`. Leer lassen, wenn kein Cloudflare-Tunnel benutzt wird — ohne Profil startet der Container gar nicht. |

`POSTGRES_PASSWORD` ist bewusst kein `:?`-Pflichtwert wie die drei Secrets:
PostgreSQL setzt das Passwort **einmalig** beim Initialisieren eines leeren
Volumes. Ein neuer Wert gegen ein bestehendes Volume ändert nichts am Passwort in
der Datenbank — er macht nur, dass Core sich nicht mehr verbinden kann. Wer es
ändern will, tut das zuerst per `ALTER USER` in `psql` und dann hier.

### Routing: vier Rollen

Traefik verteilt nach Rolle, nicht nach aufgezählten Pfaden. Vier Regeln, jede mit
genau einer Aussage:

| Priorität | Route | Regel | Dienst |
| --- | --- | --- | --- |
| 30 | `ingest` | ``PathPrefix(`/ingest`)`` | Streak-Importer |
| 20 | `docs` | ``PathPrefix(`/docs`)`` | Dokumentation |
| 10 | `api` | ``PathPrefix(`/api`) \|\| Path(`/health`)`` | API-Gateway |
| 1 | `workspace` | ``PathPrefix(`/`)`` | Dashboard |

Höhere Priorität gewinnt. Jede Route beschreibt nur, was ihr gehört; der
**Workspace nimmt alles Übrige** — denn genau das ist eine UI: der Standardfall.

Vorher stand in jeder Regel derselbe Host-Ausdruck und dahinter eine Aufzählung von
Pfaden. Die des Dashboards lautete ``Path(`/`) || PathPrefix(`/_next`)`` und traf
damit 2 der 12 Routen, die die App tatsächlich baut: `/explorer`, `/connectors`,
`/auth/callback` und jeder Reload liefen in Traefiks 404, während Navigation im
Browser funktionierte. Die Seiten einer Single-Page-App im Proxy aufzuzählen ist
eine Liste, die beim nächsten Feature veraltet — ein Catch-all nicht.

**Kein `Host()` mehr.** Der Ausdruck war viermal dieselbe Deployment-Tatsache, und
das angehängte ``|| Host(`localhost`)`` entschied ohnehin fast nichts. Hostnamen
durchsetzen gehört dorthin, wo TLS endet: Tunnel, Coolify-Ingress oder Reverse
Proxy. `PUBLIC_HOST` behält seine Aufgabe (Traefik-Auslieferung, CORS-Standard) —
es muss nur nicht mehr in Proxy-Regeln kopiert werden.

Ebenfalls entfallen ist ``PathPrefix(`/api/v1/ingest/streak`)`` in der
Ingest-Regel: dieser Pfad überlagerte bei Priorität 100 die API-Route, und das
Gateway leitet ihn selbst an den Importer weiter — dort bekommt er zugleich seine
`X-Request-ID`. Authentifiziert wird der API-Key in beiden Fällen vom Importer.

### Netzwerkgrenzen

Öffentlich gehört **nur Traefik** (`QS_HTTP_PORT`) und dadurch Gateway, Dashboard
und Dokumentation; erreichbar bleiben außerdem die beiden Importer, an die externe
Geräte senden. Zwei Dinge sind gegenüber dem alten Produktions-Compose bewusst
anders: Core veröffentlicht keine Host-Ports mehr, und das Traefik-Dashboard hängt
auf Loopback. Begründung und Zugriffsweg unter
[Netzwerkgrenzen](operations.md#netzwerkgrenzen).

### Wo das Dashboard seine API sucht

Next.js ersetzt `NEXT_PUBLIC_*` beim **Build** im Client-Bundle. In einem
veröffentlichten Image lässt sich `NEXT_PUBLIC_API_URL` zur Laufzeit deshalb nicht
mehr setzen — die Variable am Container hat keine Wirkung, und
`docker-compose.prod.yml` setzt sie folgerichtig nicht.

Das Release-Image wird absichtlich **ohne** diese Variable gebaut. Ohne sie fällt
die UI auf `window.location.origin` zurück, also auf Traefik, der `/api` an das
Gateway routet. Ein Image passt damit auf jeden Host.

Wer die UI unter einer anderen Origin als die API betreiben muss, baut das Image
selbst:

```bash
docker build --build-arg NEXT_PUBLIC_API_URL=https://api.example.com \
  -t meine-registry/dashboard:1.0.0 apps/dashboard
```

### Aktualisieren

```bash
$EDITOR .env    # QS_VERSION auf die neue Version
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml run --rm core alembic upgrade head
```

Die Importer sind zustandslos und dürfen jederzeit ersetzt werden. Der Reihenfolge
wegen wichtig ist nur die Migration: erst die neuen Images, dann `alembic upgrade
head` — nie umgekehrt.

### Zurückrollen

`QS_VERSION` auf die vorige Version, `pull`, `up -d`. Das funktioniert, weil die
Images unter ihrem Versions-Tag unverändert liegen bleiben.

**Nur die Datenbank rollt nicht mit.** Enthielt das Release dazwischen eine
Migration, muss sie vor dem Zurückrollen zurückgenommen werden, sonst trifft alter
Code auf ein neueres Schema:

```bash
docker compose -f docker-compose.prod.yml run --rm core alembic downgrade -1
```

Jede Migration in diesem Repository hat ein funktionierendes `downgrade()` — Regel 7
verlangt es, und die CI prüft es bei jedem Lauf. Welche Migration ein Release
mitgebracht hat, steht im Changelog des Releases.

### Prüfen, ob es wirklich läuft

Von außen, nicht von der Maschine selbst:

```bash
OWNER_EMAIL=du@example.com OWNER_PASSWORD='…' \
  bash tools/smoke_deployment.sh https://dein-host.example
```

Ohne Zugangsdaten laufen die unauthentifizierten Prüfungen. Mit ihnen meldet das
Skript zusätzlich, was das Deployment über seine eigene Konfiguration denkt — das
ist der Teil, der „antwortet" von „ist richtig eingerichtet" unterscheidet. Das
Dashboard zeigt dieselben Befunde Inhabern als Banner, siehe
[Selbstauskunft im Dashboard](operations.md#selbstauskunft-im-dashboard).

## Weiterhin mit Coolify

Der Stack ist nicht mehr Coolify-spezifisch, läuft dort aber weiter: als Docker
Compose-Anwendung mit `docker-compose.prod.yml` als Compose-Datei. Die Variablen
aus `.env` gehören dann in die Environment-Variablen der Anwendung, und Coolify
zieht die Images, statt sie zu bauen. `QS_VERSION` ist damit der einzige Wert, den
ein Deployment für ein Update ändern muss.

## Wenn es klemmt

| Symptom | Ursache |
| --- | --- |
| `denied` beim `pull` | Die Packages sind noch privat. Siehe [Sichtbarkeit der Packages](#einmalig-sichtbarkeit-der-packages). |
| `required variable JWT_SECRET is missing` | Genau so gedacht. Die drei Secrets setzen. |
| `manifest unknown` | `QS_VERSION` zeigt auf eine Version, für die es kein Release gibt. |
| Importer laufen, importieren aber nichts | `INTERNAL_SERVICE_SECRET` muss auf Core **und allen acht Importern** identisch sein — im alten Produktions-Compose fehlte er bei den Importern, wodurch jeder Credential-Abruf abgelehnt wurde. |
| Dashboard lädt, API-Aufrufe scheitern | Die UI ruft ihre eigene Origin auf. Prüfen, dass Traefik `/api` an das Gateway routet und `PUBLIC_HOST` stimmt. |
| Der Release-Workflow bricht sofort ab | Entweder existiert das Tag schon, oder die CI ist für diesen Commit nicht grün. Der Fehlertext sagt welches von beidem. |

Weitere Fehlerbilder unter [Fehlerbehebung](troubleshooting.md).
