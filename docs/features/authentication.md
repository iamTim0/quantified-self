# Authentication, sessions and tenant resolution

## Overview

The platform has two separate worlds of sign-in:

- **User sessions** for the dashboard (access token + refresh token).
- **Internal service credentials** for the traffic between the importers and Core.

The two are signed with different keys and have different audiences, so that a compromised importer
cannot issue user tokens.

| | User | Internal service |
| --- | --- | --- |
| Signing key | `JWT_SECRET` | `INTERNAL_SERVICE_SECRET` |
| `aud` | `qs-api` | `qs-internal` |
| `token_type` | `access` | `service` |
| Valid on | all of `/api/v1/data/*` | `/api/v1/internal/*` only |

## How the token travels: cookie or header

There are exactly two ways, and they are meant for different callers:

| Caller | Transport | Needs CSRF protection |
| --- | --- | --- |
| Browser (dashboard) | the `qs_access` cookie, `HttpOnly` | yes — a double-submit token |
| Services, scripts, tests | `Authorization: Bearer <jwt>` | no |

The cookie is `HttpOnly` and therefore not readable by JavaScript. An XSS flaw in the interface can no
longer read the session out and exfiltrate it.

But because the browser attaches cookies to *every* request to this origin — including one triggered by
somebody else's page — a second protection comes with it:

- `SameSite=Lax` stops the cookie travelling on cross-site subrequests. `Lax` rather than `Strict`, so
  that the redirect back from the OIDC provider still arrives signed in.
- A **double-submit token**: the `qs_csrf` cookie is deliberately *not* `HttpOnly`. The interface reads
  it and sends the same value back in the `X-CSRF-Token` header. Another site can have the cookie sent
  along, but cannot read it — the same-origin policy prevents that — and therefore cannot form the
  matching header.

The header route needs no CSRF protection: no browser attaches an `Authorization` header by itself.

For **state-changing** requests (`POST`, `PUT`, `PATCH`, `DELETE`) over the cookie route,
`X-CSRF-Token` is mandatory. Missing, or contradicting the cookie → `403`.

## The tenant comes from the token and nowhere else

The tenant is **always** derived from the validated token — whether that came from the cookie or the
header. An `X-Tenant-ID` header may agree with the claim but must never override it; a contradiction is
a `403`.

```http
GET /api/v1/data/metrics
Authorization: Bearer <jwt>
```

The Gateway still injects `X-Tenant-ID` for downstream services, but Core validates the token
independently a second time. That makes the Gateway an additional filtering stage, not the only
safeguard.

!!! note "Internal endpoints are not publicly reachable"
    `/api/v1/internal/*` hands out decrypted connector credentials and is **not** passed through to the
    outside by the Gateway. Importers reach Core directly over the internal network with a service
    credential.

## Validated claims

For every user token these are checked: the signature, the issuer (`iss = qs-core`), the audience
(`aud = qs-api`), the expiry, the token type, and the presence of `user_id`, `tenant_id` and `jti`. If
the role is missing, the lowest permission applies (`member`) — not the highest.

Failure behaviour:

- missing or invalid token → `401`
- valid token without a sufficient role → `403`

## Sessions: lifetimes and renewal

| Credential | Cookie | Lifetime | Revocable |
| --- | --- | --- | --- |
| Access token | `qs_access` (`HttpOnly`, path `/`) | 12 hours (`ACCESS_TOKEN_TTL_MINUTES`) | yes, through the `jti` denylist |
| Refresh token | `qs_refresh` (`HttpOnly`, path `/api/v1/auth`) | 30 days (`REFRESH_TOKEN_TTL_DAYS`) | yes, immediately |
| CSRF token | `qs_csrf` (readable) | 30 days | rotates on every renewal |

Refresh tokens are **not** JWTs but random, opaque strings. Only their SHA-256 hash is stored, so that a
database leak is not directly usable against the API.

The refresh cookie is restricted to `/api/v1/auth`. It therefore does not ride along on every metric
query, only where it is needed.

The cookie attributes are configured with `COOKIE_SECURE` (`true` by default), `COOKIE_SAMESITE` (`lax`
by default) and `COOKIE_DOMAIN` (empty by default, meaning host-only). `Secure=true` works locally too,
because browsers treat `http://localhost` as a trustworthy origin.

### Rotation is single-use

```http
POST /api/v1/auth/refresh
Cookie: qs_refresh=<token>; qs_csrf=<csrf>
X-CSRF-Token: <csrf>
```

Non-browser clients can pass the token in the body instead (`{ "refresh_token": "<token>" }`).

Every renewal spends the token that was presented and issues a new pair. If an already spent token is
presented again, that counts as an indication of theft: **all** of that user's sessions are revoked
rather than another one being issued.

## Logout

```http
POST /api/v1/auth/logout
Cookie: qs_access=<jwt>; qs_refresh=<token>; qs_csrf=<csrf>
X-CSRF-Token: <csrf>
{ "all_sessions": false }
```

- The access token's `jti` goes on the denylist; further requests with it → `401`.
- The refresh token is revoked.
- With `all_sessions: true` every session of the user is ended — see
  [Ending every session](#ending-every-session) for why that takes more than revoking the refresh
  tokens.
- All three cookies are deleted — including when the token presented had already expired or was
  unreadable. Otherwise a cookie would be left behind and the next page view would look signed in again.
- The response is always `204`, even for an invalid or missing token. Logout has to work when the client
  has lost its token, and must not reveal whether a presented token was genuine.

The dashboard itself no longer holds any credentials it could delete — the session *is* the cookie. A
`401` from any request ends the session immediately, and a tab that comes back into the foreground asks
the server again instead of trusting its last rendered state. **A page refresh after signing out does not
sign you back in.**

!!! warning "The dev-token endpoint is gone"
    `GET /api/v1/auth/dev-token` no longer exists. It issued `owner` tokens valid for 365 days for any
    tenant passed as a query parameter, and the dashboard called it automatically whenever no token was
    stored — which is exactly why signing out signed you straight back in. For local development,
    register and sign in normally.

### Ending every session

`all_sessions: true`, a password change and a detected refresh-token replay all trigger the same thing —
and for a long time that did not do what it promises. Only the refresh tokens were revoked. That prevents
a *new* session being created, but every access token already issued stayed valid for up to twelve hours:
after a password change, after a detected theft, and after the provider signed the user out.

The denylist cannot do this. It is indexed on `jti`, and a `jti` only becomes known when the token is
presented — "every outstanding token of this account" is not a set that can be enumerated. Instead,
`users` now carries a `sessions_valid_from` column. Every request compares it against its token's `iat`;
anything from before is rejected. One row, one comparison, every token.

A new token issued after the cut-off is unaffected — so signing in works again immediately.

### Signing out at the provider

Anyone who signed in through an external provider has a second, separate session there. End only the
local one and the next click on "Sign in with …" goes straight back in without a prompt — which makes the
sign-out look ineffective.

So if the discovery document holds an `end_session_endpoint`, `/api/v1/auth/logout` answers `200` with an
`end_session_url` for the interface to follow. Without a linked provider it stays a `204`.

Deliberately **without** `id_token_hint`: that would write the user's identity into a URL that ends up in
the browser history and in every proxy log. The price is that some providers ask which account should be
signed out — the more harmless failure mode.

`POST_LOGOUT_REDIRECT_URI` sets where the user lands after signing out. It has to be registered with the
provider.

The other direction — the provider ends the session and tells us about it — is described in
[back-channel logout](oidc.md#back-channel-logout).

## Warnings in the dashboard

Configuration and access problems no longer live only in a log line, a commit message or this
documentation — they appear as a banner above the content, on every tab. A platform that signs sessions
with a key printed in its own source code should say so where the operator is looking.

`GET /api/v1/data/system/warnings` returns the list. What is reported:

| Code | Severity | Trigger |
| --- | --- | --- |
| `insecure_jwt_secret` | critical | `JWT_SECRET` is unset or a published default value |
| `insecure_encryption_key` | critical | the same for `ENCRYPTION_KEY` — with the note to re-encrypt **first** |
| `insecure_internal_secret` | critical | the same for `INTERNAL_SERVICE_SECRET` |
| `password_published` | critical | The hash of your own password was in a published source |
| `registration_open` | warning | `ALLOW_REGISTRATION` is on |
| `cookies_not_secure` | warning | `COOKIE_SECURE` is off |
| `development_environment` | info | explains why the services start despite the points above |

Three properties are deliberate:

- **Only owners and administrators see the deployment warnings.** Naming *which* key is weak is itself a
  small disclosure.
- **`password_published` is seen by the person affected, regardless of role.** Withholding "your password
  is public" from somebody because they are only a member would be absurd.
- **Dismissing lasts a day, per code.** A permanent "do not show again" on "your signing key is
  public" is how it stays public, and hiding it only until the next page load is how a banner gets
  ignored instead of read. A day is the compromise: acknowledging a warning is worth something, and it
  still comes back until the thing is fixed. Per code, so a *new* problem arrives immediately even
  while an old one is hidden. Kept in `localStorage`, which is per browser rather than per account —
  the same signing key is public for everybody who can see it, so there is nothing to synchronise.
  Every warning also names a command or a setting rather than giving advice — "consider rotating your
  secrets" is the form nobody follows.

A secret's value is never printed, only the variable's name. Otherwise the warning about a weak key would
be a second way to read it.

The payloads are English, and each carries a stable `code`: the dashboard renders its own wording for a
code it knows and falls back to the server's text for one it does not. A service does not localize its own
output.

### How `password_published` knows what is public

Earlier versions created an account in `infra/db/init.sql` with a bcrypt hash shipped alongside. Whoever
had the repository had the hash and the address to go with it; bcrypt delays an attack, it does not
prevent one. The account and the history are cleaned up — which does not make a password unseen again. An
account that **still uses** such a password is warned on every sign-in until it is changed.

What is stored are SHA-256 digests of the affected hashes, not the hashes themselves. Checking in a real
bcrypt hash in order to recognize a leaked bcrypt hash would republish exactly what is being warned
about — and `.agents/scripts/check_private_info.py` would rightly refuse it.

## Registration is closed by default

`ALLOW_REGISTRATION` is `false`. The first account is created with `python -m core.create_owner`; the full
procedure is under [Creating the first account](../operations.md#creating-the-first-account).

Two properties of that command are deliberate: the password comes from a prompt and never from an
argument, and a second call with the same address aborts instead of quietly replacing the existing
password.

## The server-side route guard

A deep link to `/profile` without a session no longer renders the shell first, waits for
`/api/v1/auth/me` and then swaps in the sign-in form — with `/profile` still in the address bar.
`apps/dashboard/src/proxy.ts` (Next 16's new name for `middleware.ts`) redirects to `/?next=<target>`
beforehand; after signing in you carry on there.

What it checks is `qs_csrf`, not the access token. That expires after twelve hours while the session lasts
thirty days — so redirecting on a missing `qs_access` would throw every returning user out of a working
session. `qs_refresh` is restricted to `/api/v1/auth` and is not sent on a page navigation at all.
`qs_csrf` sits on `/`, lives as long as the refresh token, and is not a credential in its own right.

!!! note "Not an access control"
    The guard is a correction to the address bar and to what is rendered, not authorization — Next.js's
    own documentation explicitly advises against using it as one. Every byte of tenant data comes from a
    request that the Gateway and Core validate. Forge the cookie and you get the same empty shell and a
    `401`.

## Changing a password

`POST /api/v1/auth/change-password` changes the password of the **calling** user (resolved from `user_id`
in the token) and then revokes every session of that account, including the token just used.

## Changing account and workspace details

The signed-in user can edit their own display name and email address from the profile settings. Owners and
administrators can also rename the workspace; members can see the current name but cannot change it.

```http
PUT /api/v1/auth/me
Content-Type: application/json
X-Tenant-ID: <the token's tenant id>

{
  "name": "New display name",
  "email": "new-address@example.test",
  "workspace_name": "New workspace name"
}
```

The tenant and user are resolved from the authenticated token; the header is only checked for agreement and
never selects another workspace. Email addresses are normalized case-insensitively and remain globally unique.
Changing an email revokes older sessions and refreshes the current browser session with the new address.
The existing account and tenant columns are reused, so no manual data migration is needed for this feature.

## Correlation

Every request carries an `X-Request-ID`, which is propagated across the Gateway, Core, the NATS events and
the importers, and printed in every log as `[req_id=…]`. Sign-in, sign-out and token renewal can be
followed through it.

## Known limitations

- The actual access control still only takes effect at the network request. The
  [route guard](#the-server-side-route-guard) corrects the address bar and what is rendered; it authorizes
  nothing.
- External sign-in over OIDC is available but off by default; see [External sign-in (OIDC)](oidc.md).
- The roles (`owner`, `admin`, `member`) are evaluated for managing API keys and sign-in providers.
