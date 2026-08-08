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
- Mit `all_sessions: true` werden alle Sessions des Nutzers beendet — siehe
  [Alle Sessions beenden](#alle-sessions-beenden) dazu, warum das mehr braucht als
  das Widerrufen der Refresh Tokens.
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

### Alle Sessions beenden

`all_sessions: true`, eine Passwortänderung und ein erkannter Refresh-Token-Replay
lösen alle dasselbe aus — und das tat lange nicht, was es verspricht. Widerrufen
wurden nur die Refresh Tokens. Damit lässt sich keine *neue* Sitzung mehr
erzeugen, aber jedes bereits ausgestellte Access Token blieb bis zu zwölf Stunden
gültig: nach einer Passwortänderung, nach einem erkannten Diebstahl und nach einer
Abmeldung durch den Anbieter.

Die Denylist kann das nicht leisten. Sie ist auf `jti` indiziert, und ein `jti`
wird erst bekannt, wenn das Token vorgelegt wird — „alle offenen Tokens dieses
Kontos" ist keine Menge, die sich aufzählen lässt. Stattdessen trägt `users` jetzt
eine Spalte `sessions_valid_from`. Jeder Request vergleicht sie mit dem `iat`
seines Tokens; alles davor wird abgelehnt. Eine Zeile, ein Vergleich, alle Tokens.

Ein neues Token nach dem Stichzeitpunkt ist davon nicht betroffen — Anmelden
funktioniert also sofort wieder.

### Abmelden beim Anbieter

Wer sich über einen externen Anbieter angemeldet hat, hat dort eine zweite,
eigene Sitzung. Wird nur die lokale beendet, führt der nächste Klick auf
„Anmelden mit …" ohne Rückfrage sofort wieder hinein — die Abmeldung sieht dann
wirkungslos aus.

Ist im Discovery-Dokument ein `end_session_endpoint` hinterlegt, antwortet
`/api/v1/auth/logout` deshalb mit `200` und einem `end_session_url`, dem die
Oberfläche folgt. Ohne verknüpften Anbieter bleibt es beim `204`.

Bewusst **ohne** `id_token_hint`: der würde die Identität der Nutzerin in eine URL
schreiben, die im Browserverlauf und in jedem Proxy-Log landet. Der Preis ist,
dass manche Anbieter nachfragen, welches Konto abgemeldet werden soll — das ist
der harmlosere Fehlerfall.

Das Ziel nach der Abmeldung stellt `POST_LOGOUT_REDIRECT_URI` ein. Es muss beim
Anbieter registriert sein.

Die Gegenrichtung — der Anbieter beendet die Sitzung und teilt uns das mit —
beschreibt [Back-Channel-Logout](oidc.md#back-channel-logout).

## Registrierung ist standardmäßig geschlossen

`ALLOW_REGISTRATION` steht auf `false`. Das erste Konto wird mit
`python -m core.create_owner` angelegt; der vollständige Ablauf steht unter
[Das erste Konto anlegen](../operations.md#das-erste-konto-anlegen).

Zwei Eigenschaften des Befehls sind Absicht: das Passwort kommt aus einer
Eingabeaufforderung und nie aus einem Argument, und ein zweiter Aufruf mit
derselben Adresse bricht ab, statt das vorhandene Passwort stillschweigend zu
ersetzen.

## Serverseitiger Route-Guard

Ein Deep-Link auf `/profile` ohne Sitzung rendert nicht mehr erst das Grundgerüst,
wartet auf `/api/v1/auth/me` und tauscht dann das Anmeldeformular ein — mit
`/profile` weiterhin in der Adresszeile. `apps/dashboard/src/proxy.ts` (in Next 16
der neue Name für `middleware.ts`) leitet vorher auf `/?next=<Ziel>` um; nach der
Anmeldung geht es dort weiter.

Geprüft wird `qs_csrf`, nicht das Access Token. Das läuft nach zwölf Stunden ab,
während die Sitzung dreißig Tage hält — auf ein fehlendes `qs_access` umzuleiten
würde also jede zurückkehrende Nutzerin aus einer funktionierenden Sitzung werfen.
`qs_refresh` ist auf `/api/v1/auth` beschränkt und wird bei einer Seitennavigation
gar nicht gesendet. `qs_csrf` liegt auf `/`, lebt so lange wie der Refresh Token
und ist für sich genommen kein Zugangsnachweis.

!!! note "Kein Zugriffsschutz"
    Der Guard ist eine Korrektur an Adresszeile und Darstellung, keine
    Autorisierung — Next.js' eigene Dokumentation rät ausdrücklich davon ab, ihn
    als solche zu verwenden. Jedes Byte an Tenant-Daten kommt aus einem Request,
    den Gateway und Core prüfen. Wer das Cookie fälscht, bekommt dasselbe leere
    Grundgerüst und ein `401`.

## Passwortänderung

`POST /api/v1/auth/change-password` ändert das Passwort des **aufrufenden** Nutzers
(aufgelöst über `user_id` aus dem Token) und widerruft anschließend alle Sessions
dieses Kontos, einschließlich des gerade verwendeten Tokens.

## Korrelation

Jeder Request trägt eine `X-Request-ID`, die über Gateway, Core, NATS-Events und
Importer propagiert und in allen Logs als `[req_id=…]` ausgegeben wird. Login,
Logout und Token-Erneuerung sind darüber nachvollziehbar.

## Bekannte Einschränkungen

- Der eigentliche Zugriffsschutz greift weiterhin erst im Netzwerk-Request. Der
  [Route-Guard](#serverseitiger-route-guard) korrigiert Adresszeile und Darstellung,
  er autorisiert nichts.
- Externe Anmeldung über OIDC ist verfügbar, aber standardmäßig deaktiviert; siehe
  [Externe Anmeldung (OIDC)](oidc.md).
- Rollen (`owner`, `admin`, `member`) werden für die Verwaltung der API-Keys und
  der Anmeldeanbieter ausgewertet.
