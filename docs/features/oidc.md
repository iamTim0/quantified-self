# Externe Anmeldung (OIDC)

Zusätzlich zu E-Mail und Passwort kann die Anmeldung über beliebige
OpenID-Connect-Anbieter erfolgen. **Google ist dabei nur eine Konfigurationszeile**
— es gibt keinen anbieterspezifischen Code.

## Ablauf

Authorization Code Flow mit PKCE (S256):

1. Die Nutzerin klickt auf „Mit … anmelden".
2. Die Anwendung fordert bei Core eine Autorisierungs-URL an. Core erzeugt
   `state`, `nonce` und einen PKCE-Verifier und **speichert sie serverseitig**.
   Der Browser erhält nur die URL und den undurchsichtigen `state`.
3. Der Anbieter authentifiziert die Nutzerin und leitet mit `code` und `state`
   zurück.
4. Die Anwendung sendet beides an Core. Core löst den gespeicherten Eintrag
   ein — einmalig — und tauscht den Code samt Verifier gegen Tokens.
5. Core validiert das `id_token` und stellt dieselbe Sitzung aus wie bei einer
   Anmeldung mit Passwort.

Weil Verifier und `nonce` den Browser nie erreichen, nützt ein abgefangener
`code` einem Angreifer nichts.

## Was geprüft wird

| Prüfung | Warum |
| --- | --- |
| `state` | serverseitig, einmalig verwendbar — ohne sie ist der Callback fälschbar (CSRF-Login) |
| PKCE `S256` | ein abgefangener Code ist ohne den Verifier wertlos |
| Signatur | gegen das JWKS des Anbieters; nur asymmetrische Verfahren |
| `iss` | muss exakt dem konfigurierten Issuer entsprechen |
| `aud` | muss unsere Client-ID sein |
| `exp` / `iat` | mit 60 Sekunden Toleranz für Uhrenabweichung |
| `nonce` | bindet das Token an genau diese Anfrage |
| `redirect_uri` | exakter Zeichenkettenvergleich |

`alg: none` und symmetrische Verfahren werden abgelehnt. Die Discovery-URL wird
gegen den konfigurierten Issuer geprüft, damit ein Dokument nicht auf einen anderen
Anbieter umleiten kann. Die `redirect_uri` wird exakt verglichen — Präfixvergleiche
sind der übliche Weg, wie Open Redirects entstehen.

## Kontenverknüpfung

Die Identität wird über **`(Anbieter, sub)`** geführt, niemals über die
E-Mail-Adresse. Adressen wechseln den Besitzer und können neu vergeben werden;
eine Zuordnung darüber ist genau der Weg zur Kontoübernahme.

Daraus folgen vier Fälle:

| Situation | Verhalten |
| --- | --- |
| Verknüpfung existiert | Anmeldung, Sitzung wird ausgestellt |
| Kein Konto, `allow_signup` aktiv, E-Mail verifiziert | Neues Konto samt Arbeitsbereich |
| Kein Konto, `allow_signup` inaktiv | `403` |
| **Konto mit dieser E-Mail existiert, aber ohne Verknüpfung** | **`409` — keine automatische Übernahme** |

Der letzte Fall ist Absicht. Wer das Konto besitzt, meldet sich regulär an und
verknüpft den Anbieter bewusst in den Einstellungen. Eine automatische
Zusammenführung würde jedem, der einen Anbieter dazu bringt, diese Adresse zu
bestätigen, das fremde Konto überlassen.

Ist `require_verified_email` gesetzt (Standard) und der Anbieter bestätigt die
Adresse nicht als verifiziert, wird die Anmeldung abgelehnt.

### Verknüpfung entfernen

Der letzte verbleibende Anmeldeweg lässt sich nicht entfernen: Ohne Passwort und
ohne weiteren Anbieter wäre das Konto dauerhaft unerreichbar. Die Anwendung
antwortet dann mit `409`.

## Anbieter konfigurieren

Ein Anbieter ist eine Zeile in `oidc_providers`:

| Feld | Bedeutung |
| --- | --- |
| `slug` | URL-sicherer Schlüssel, z. B. `google` |
| `display_name` | Beschriftung der Schaltfläche |
| `issuer` | Basis-URL; Discovery erfolgt darunter |
| `client_id` | Client-ID beim Anbieter |
| `encrypted_client_secret` | Fernet-verschlüsselt; öffentliche Clients ohne Secret sind zulässig, weil PKCE sie schützt |
| `scopes` | Standard `openid email profile` |
| `redirect_uri` | muss exakt übereinstimmen |
| `claims_mapping` | Abbildung abweichender Claim-Namen |
| `enabled` | steuert Sichtbarkeit und Nutzbarkeit |
| `allow_signup` | ob eine Erstanmeldung ein Konto anlegen darf |
| `require_verified_email` | ob `email_verified` verlangt wird |

Beispiel für Google:

```text
slug                   google
issuer                 https://accounts.google.com
scopes                 openid email profile
redirect_uri           https://<host>/auth/callback
require_verified_email true
```

!!! warning "Nur vertrauenswürdige Issuer eintragen"
    Ein Anbieter kann jede beliebige `email` behaupten. Ob diese Behauptung etwas
    wert ist, hängt allein davon ab, wem hier vertraut wird. `allow_signup` sollte
    nur für Anbieter aktiviert werden, deren Kontoerstellung kontrolliert ist.

## Nachvollziehbarkeit

Start, Callback und Sitzungsausstellung tragen dieselbe `X-Request-ID` wie jede
andere Anfrage. Erfolgreiche Anmeldungen werden mit Anbieter, Nutzer- und
Tenant-ID protokolliert; Tokens, Codes und Secrets niemals.

## Einschränkungen

- Es gibt noch keine Oberfläche zum Anlegen von Anbietern — die Zeile wird derzeit
  direkt in der Datenbank gepflegt.
- Ein Konto, das ausschließlich über einen Anbieter angelegt wurde, hat kein
  lokales Passwort. Bis eines gesetzt wird, ist der Anbieter der einzige Zugang.
- Abgemeldet wird nur lokal. Eine Single-Logout-Abmeldung beim Anbieter (RP-initiated
  logout) ist nicht implementiert.
