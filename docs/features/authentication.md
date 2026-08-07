# Authentifizierung, Sessions und Tenant-Zuordnung

## Überblick

Die Plattform kennt zwei getrennte Anmelde-Welten:

- **Nutzer-Sessions** für das Dashboard (Access Token + Refresh Token).
- **Interne Service-Zugangsdaten** für die Kommunikation zwischen Importern und
  Core.

Beide werden mit unterschiedlichen Schlüsseln signiert und haben unterschiedliche
Audiences, damit ein kompromittierter Importer keine Nutzer-Tokens ausstellen kann.

| | Nutzer | Interner Dienst |
| --- | --- | --- |
| Signaturschlüssel | `JWT_SECRET` | `INTERNAL_SERVICE_SECRET` |
| `aud` | `qs-api` | `qs-internal` |
| `token_type` | `access` | `service` |
| Gültig auf | allen `/api/v1/data/*` | nur `/api/v1/internal/*` |

## Wie das Token übertragen wird: Cookie oder Header

Es gibt genau zwei Wege, und sie sind für unterschiedliche Aufrufer gedacht:

| Aufrufer | Übertragung | CSRF-Schutz nötig |
| --- | --- | --- |
| Browser (Dashboard) | `qs_access`-Cookie, `HttpOnly` | ja — Double-Submit-Token |
| Dienste, Skripte, Tests | `Authorization: Bearer <jwt>` | nein |

Das Cookie ist `HttpOnly`, also für JavaScript nicht lesbar. Ein XSS-Fehler in der
Oberfläche kann die Sitzung damit nicht mehr auslesen und exfiltrieren.

Weil der Browser Cookies aber an *jeden* Request an diesen Origin anhängt — auch an
einen, den eine fremde Seite auslöst — kommt ein zweiter Schutz dazu:

- `SameSite=Lax` verhindert, dass das Cookie bei Cross-Site-Subrequests mitgeht.
  `Lax` statt `Strict`, damit die Rückleitung vom OIDC-Anbieter noch angemeldet
  ankommt.
- Ein **Double-Submit-Token**: Das Cookie `qs_csrf` ist bewusst *nicht* `HttpOnly`.
  Die Oberfläche liest es und schickt denselben Wert im Header `X-CSRF-Token`
  zurück. Eine fremde Seite kann das Cookie zwar mitsenden lassen, es aber nicht
  lesen — die Same-Origin-Policy verhindert das — und deshalb den passenden Header
  nicht bilden.

Der Header-Weg braucht keinen CSRF-Schutz: Kein Browser hängt von sich aus einen
`Authorization`-Header an.

Bei **zustandsändernden** Requests (`POST`, `PUT`, `PATCH`, `DELETE`) über den
Cookie-Weg ist `X-CSRF-Token` Pflicht. Fehlt oder widerspricht er dem Cookie → `403`.

## Tenant-Zuordnung ausschließlich aus dem Token

Der Tenant wird **immer** aus dem validierten Token abgeleitet — gleich, ob es aus dem
Cookie oder dem Header stammt. Ein `X-Tenant-ID`-Header darf mit dem Claim
übereinstimmen, ihn aber niemals überschreiben — Widerspruch führt zu `403`.

```http
GET /api/v1/data/metrics
Authorization: Bearer <jwt>
```

Das Gateway injiziert `X-Tenant-ID` weiterhin für nachgelagerte Dienste, aber Core
prüft das Token unabhängig noch einmal selbst. Das Gateway ist damit eine zusätzliche
Filterstufe, nicht die einzige Absicherung.

!!! note "Interne Endpunkte sind nicht öffentlich erreichbar"
    `/api/v1/internal/*` gibt entschlüsselte Connector-Zugangsdaten heraus und wird
    vom Gateway **nicht** nach außen weitergereicht. Importer erreichen Core direkt
    über das interne Netz mit einem Service-Credential.

## Validierte Claims

Bei jedem Nutzer-Token werden geprüft: Signatur, Aussteller (`iss = qs-core`),
Audience (`aud = qs-api`), Ablaufzeit, Token-Typ sowie das Vorhandensein von
`user_id`, `tenant_id` und `jti`. Fehlt die Rolle, gilt die geringste Berechtigung
(`member`) — nicht die höchste.

Fehlerverhalten:

- fehlendes oder ungültiges Token → `401`
- gültiges Token ohne ausreichende Rolle → `403`

## Sessions: Laufzeiten und Erneuerung

| Credential | Cookie | Laufzeit | Widerrufbar |
| --- | --- | --- | --- |
| Access Token | `qs_access` (`HttpOnly`, Pfad `/`) | 12 Stunden (`ACCESS_TOKEN_TTL_MINUTES`) | ja, über `jti`-Denylist |
| Refresh Token | `qs_refresh` (`HttpOnly`, Pfad `/api/v1/auth`) | 30 Tage (`REFRESH_TOKEN_TTL_DAYS`) | ja, sofort |
| CSRF-Token | `qs_csrf` (lesbar) | 30 Tage | rotiert bei jeder Erneuerung |

Refresh Tokens sind **keine** JWTs, sondern zufällige, undurchsichtige
Zeichenketten. Gespeichert wird nur ihr SHA-256-Hash, damit ein Datenbankleck nicht
direkt gegen die API einsetzbar ist.

Das Refresh-Cookie ist auf `/api/v1/auth` eingeschränkt. Es fährt damit nicht bei
jeder Metrik-Abfrage mit, sondern nur dort, wo es gebraucht wird.

Konfiguration der Cookie-Attribute: `COOKIE_SECURE` (Standard `true`),
`COOKIE_SAMESITE` (Standard `lax`), `COOKIE_DOMAIN` (Standard leer = host-only).
`Secure=true` funktioniert auch lokal, weil Browser `http://localhost` als
vertrauenswürdigen Origin behandeln.

### Rotation ist einmalig

```http
POST /api/v1/auth/refresh
Cookie: qs_refresh=<token>; qs_csrf=<csrf>
X-CSRF-Token: <csrf>
```

Nicht-Browser-Clients können den Token stattdessen im Body mitgeben
(`{ "refresh_token": "<token>" }`).

Jede Erneuerung verbraucht den präsentierten Token und gibt ein neues Paar aus. Wird
ein bereits verbrauchter Token erneut vorgelegt, gilt das als Hinweis auf einen
Diebstahl: **alle** Sessions dieses Nutzers werden widerrufen, statt eine weitere
auszustellen.

## Logout

```http
POST /api/v1/auth/logout
Cookie: qs_access=<jwt>; qs_refresh=<token>; qs_csrf=<csrf>
X-CSRF-Token: <csrf>
{ "all_sessions": false }
```

- Der `jti` des Access Tokens landet auf der Denylist; weitere Requests damit → `401`.
- Der Refresh Token wird widerrufen.
- Mit `all_sessions: true` werden alle Sessions des Nutzers beendet.
- Alle drei Cookies werden gelöscht — auch dann, wenn das präsentierte Token schon
  abgelaufen oder unlesbar war. Andernfalls bliebe ein Cookie zurück und der nächste
  Seitenaufruf sähe wieder angemeldet aus.
- Die Antwort ist immer `204`, auch bei ungültigem oder fehlendem Token. Logout muss
  auch dann funktionieren, wenn der Client sein Token verloren hat, und darf nicht
  verraten, ob ein präsentiertes Token echt war.

Das Dashboard hält selbst keine Anmeldedaten mehr, die es löschen könnte — die
Sitzung *ist* das Cookie. Ein `401` aus einem beliebigen Request beendet die Session
sofort, und ein Tab, der wieder in den Vordergrund kommt, fragt den Server erneut,
statt seinem zuletzt gerenderten Zustand zu vertrauen. **Ein Seiten-Refresh nach dem
Logout meldet nicht wieder an.**

!!! warning "Entfernter Dev-Token-Endpunkt"
    `GET /api/v1/auth/dev-token` gibt es nicht mehr. Er stellte 365 Tage gültige
    `owner`-Tokens für jeden beliebigen als Query-Parameter übergebenen Tenant aus,
    und das Dashboard rief ihn automatisch auf, sobald kein Token gespeichert war —
    genau deshalb war man nach dem Logout sofort wieder angemeldet. Für lokale
    Entwicklung bitte regulär registrieren und anmelden.

## Passwortänderung

`POST /api/v1/auth/change-password` ändert das Passwort des **aufrufenden** Nutzers
(aufgelöst über `user_id` aus dem Token) und widerruft anschließend alle Sessions
dieses Kontos, einschließlich des gerade verwendeten Tokens.

## Korrelation

Jeder Request trägt eine `X-Request-ID`, die über Gateway, Core, NATS-Events und
Importer propagiert und in allen Logs als `[req_id=…]` ausgegeben wird. Login,
Logout und Token-Erneuerung sind darüber nachvollziehbar.

## Bekannte Einschränkungen

- Der Zugriffsschutz greift erst im Netzwerk-Request, nicht schon beim Rendern: Es
  gibt keinen serverseitigen Route-Guard (in Next.js 16 über `proxy.ts`, nicht mehr
  `middleware.ts`). Geschützte Seiten rendern kurz ihr Grundgerüst, bevor
  `/api/v1/auth/me` antwortet. Daten sind davon nicht betroffen — die kommen erst
  nach der Prüfung.
- Externe Anmeldung über OIDC ist verfügbar, aber standardmäßig deaktiviert; siehe
  [Externe Anmeldung (OIDC)](oidc.md).
- Rollen (`owner`, `admin`, `member`) werden bisher nur für die Verwaltung der
  API-Keys ausgewertet.
