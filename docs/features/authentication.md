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

## Tenant-Zuordnung ausschließlich aus dem Token

Der Tenant wird **immer** aus dem validierten Bearer-Token abgeleitet. Ein
`X-Tenant-ID`-Header darf mit dem Claim übereinstimmen, ihn aber niemals
überschreiben — Widerspruch führt zu `403`.

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

| Credential | Laufzeit | Widerrufbar |
| --- | --- | --- |
| Access Token | 12 Stunden (`ACCESS_TOKEN_TTL_MINUTES`) | ja, über `jti`-Denylist |
| Refresh Token | 30 Tage (`REFRESH_TOKEN_TTL_DAYS`) | ja, sofort |

Refresh Tokens sind **keine** JWTs, sondern zufällige, undurchsichtige
Zeichenketten. Gespeichert wird nur ihr SHA-256-Hash, damit ein Datenbankleck nicht
direkt gegen die API einsetzbar ist.

### Rotation ist einmalig

```http
POST /api/v1/auth/refresh
{ "refresh_token": "<token>" }
```

Jede Erneuerung verbraucht den präsentierten Token und gibt ein neues Paar aus. Wird
ein bereits verbrauchter Token erneut vorgelegt, gilt das als Hinweis auf einen
Diebstahl: **alle** Sessions dieses Nutzers werden widerrufen, statt eine weitere
auszustellen.

## Logout

```http
POST /api/v1/auth/logout
Authorization: Bearer <jwt>
{ "refresh_token": "<token>", "all_sessions": false }
```

- Der `jti` des Access Tokens landet auf der Denylist; weitere Requests damit → `401`.
- Der Refresh Token wird widerrufen.
- Mit `all_sessions: true` werden alle Sessions des Nutzers beendet.
- Die Antwort ist immer `204`, auch bei ungültigem oder fehlendem Token. Logout muss
  auch dann funktionieren, wenn der Client sein Token verloren hat, und darf nicht
  verraten, ob ein präsentiertes Token echt war.

Im Dashboard werden zusätzlich alle lokalen Anmeldedaten gelöscht, andere Browser-Tabs
über ein `storage`-Event abgemeldet, und ein `401` aus einem beliebigen Request
beendet die Session sofort. **Ein Seiten-Refresh nach dem Logout meldet nicht wieder
an.**

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

- Tokens liegen im `localStorage` des Browsers, nicht in `httpOnly`-Cookies. Sie sind
  damit für XSS lesbar. Ein Wechsel auf Cookies mit serverseitigen Route-Guards
  (in Next.js 16 über `proxy.ts`, nicht mehr `middleware.ts`) ist offene Folgearbeit.
- Es gibt noch keine externen OIDC-Provider (Google o. Ä.); die Anmeldung erfolgt
  ausschließlich über E-Mail und Passwort.
- Rollen (`owner`, `admin`, `member`) werden bisher nur für die Verwaltung der
  API-Keys ausgewertet.
