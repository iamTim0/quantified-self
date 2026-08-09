# External sign-in (OIDC)

Besides email and password, sign-in can go through any OpenID Connect provider. **Google is only a
line of configuration** — there is no provider-specific code.

## Managing providers

Under **Profile → External sign-in providers**, owners and administrators can create, edit, enable
and delete providers. Before, that took inserting a row into `oidc_providers` — a working feature
nobody could switch on without database access.

Two properties of the client secret are chosen deliberately:

- The API never returns it. The list only shows *whether* one is stored.
- Leave the field empty while editing and the stored one is kept. Otherwise you would have to type it
  again just to change a checkbox.

The issuer's discovery document is validated on save. Validate it only later and the configuration
error turns up in the middle of somebody's sign-in, with a `502` as the only clue.

A provider that already has accounts linked to it cannot be deleted, only disabled: deleting would lock
out an account that has no password. Disabling is reversible.

## The flow

Authorization code flow with PKCE (S256):

1. The user clicks "Sign in with …".
2. The application asks Core for an authorization URL. Core generates `state`, `nonce` and a PKCE
   verifier and **stores them server-side**. The browser receives only the URL and the opaque `state`.
3. The provider authenticates the user and redirects back with `code` and `state`.
4. The application sends both to Core. Core redeems the stored entry — once — and exchanges the code,
   together with the verifier, for tokens.
5. Core validates the `id_token` and issues the same session as a password sign-in would.

Because the verifier and the `nonce` never reach the browser, an intercepted `code` is of no use to an
attacker.

## What is validated

| Check | Why |
| --- | --- |
| `state` | server-side, single-use — without it the callback can be forged (CSRF login) |
| PKCE `S256` | an intercepted code is worthless without the verifier |
| Signature | against the provider's JWKS; asymmetric algorithms only |
| `iss` | has to match the configured issuer exactly |
| `aud` | has to be our client ID |
| `exp` / `iat` | with 60 seconds of tolerance for clock skew |
| `nonce` | binds the token to this one request |
| `redirect_uri` | compared as an exact string |

`alg: none` and symmetric algorithms are rejected. The discovery URL is checked against the configured
issuer, so that a document cannot redirect to a different provider. The `redirect_uri` is compared
exactly — prefix comparisons are the usual way open redirects come about.

## Account linking

The identity is tracked by **`(provider, sub)`**, never by the email address. Addresses change owner and
can be reassigned; mapping on them is precisely the route to account takeover.

Four cases follow from that:

| Situation | Behaviour |
| --- | --- |
| The link exists | Sign-in, a session is issued |
| No account, `allow_signup` on, email verified | A new account together with a workspace |
| No account, `allow_signup` off | `403` |
| **An account with this email exists, but without a link** | **`409` — no automatic takeover** |

The last case is deliberate. Whoever owns the account signs in normally and links the provider knowingly
in the settings. An automatic merge would hand somebody else's account to anyone who can get a provider
to confirm that address.

If `require_verified_email` is set (the default) and the provider does not confirm the address as
verified, the sign-in is rejected.

### Removing a link

The last remaining way to sign in cannot be removed: with no password and no other provider the account
would be permanently unreachable. The application answers `409` in that case.

## Configuring a provider

A provider is a row in `oidc_providers`:

| Field | Meaning |
| --- | --- |
| `slug` | URL-safe key, e.g. `google` |
| `display_name` | The button's label |
| `issuer` | Base URL; discovery happens below it |
| `client_id` | The client ID at the provider |
| `encrypted_client_secret` | Fernet-encrypted; public clients without a secret are allowed, because PKCE protects them |
| `scopes` | `openid email profile` by default |
| `redirect_uri` | has to match exactly |
| `claims_mapping` | Mapping for claim names that differ |
| `enabled` | Controls visibility and usability |
| `allow_signup` | Whether a first sign-in may create an account |
| `require_verified_email` | Whether `email_verified` is required |

Example for Google:

```text
slug                   google
issuer                 https://accounts.google.com
scopes                 openid email profile
redirect_uri           https://<host>/auth/callback
require_verified_email true
```

!!! warning "Only enter issuers you trust"
    A provider can assert any `email` it likes. Whether that assertion is worth anything depends entirely
    on who is trusted here. `allow_signup` should only be enabled for providers whose account creation is
    controlled.

## Back-channel logout

The other direction from [signing out at the provider](authentication.md#signing-out-at-the-provider):
the session ends **at the provider** — somebody signs out of Google, an administrator disables the
account, a device is withdrawn — and the provider tells us with a signed logout token.

Until now nobody was listening. The local session carried on to its own expiry: up to thirty days after
the identity behind it was withdrawn.

```http
POST /api/v1/auth/oidc/<slug>/backchannel-logout
Content-Type: application/x-www-form-urlencoded

logout_token=<jwt>
```

The caller is a server with no session here, so the endpoint is necessarily unauthenticated. Everything
rests on validating the token:

| Check | Why |
| --- | --- |
| The signature against the JWKS | without it anyone could end arbitrary sessions |
| `iss` | another provider may not end anything here |
| `aud` | has to be our client ID |
| **no `nonce`** | a `nonce` means this is an ID token. Otherwise a token intercepted during *sign-in* could be replayed as a sign-out |
| `events` contains `…/backchannel-logout` as an object | distinguishes a logout token from any other signed token |
| `iat` at most two minutes old | see below |
| `sub` or `sid` present | otherwise the token names nobody |

The response is `200` with `Cache-Control: no-store`, `400` for an invalid token, and `503` when the
provider's keys are not reachable at that moment. That distinction matters: `400` means "do not retry",
`503` means "come back later". We never act on a token we cannot verify — otherwise an outage at the
provider would be enough to end other people's sessions with plausible-looking JSON.

The sign-out takes effect through the same mechanism as
[ending every session](authentication.md#ending-every-session). Revoking only the refresh tokens would
leave the session running for another twelve hours — which is precisely what this feature exists against.

### Two deliberate decisions

**Every session of the account is always ended**, even when the token names only one through `sid`. Our
access tokens are not bound to any provider session; honouring `sid` would claim a precision we do not
have. Signing out too much signs a second window out early; signing out too little leaves a session
running that the user believes is over. So the provider has to send `sub`; a token with only `sid` is
rejected with `400` rather than guessed at.

**There is no `jti` store against replays.** Revoking an already revoked session changes nothing. A replay
would only become dangerous if it reached across a later, legitimate sign-in — and the time window on
`iat` rules exactly that out, without running a second table.

### Setting it up

Enter this at the provider as the `backchannel_logout_uri`:

```text
https://<host>/api/v1/auth/oidc/<slug>/backchannel-logout
```

`backchannel_logout_session_required` has to stay **off** — that is the setting which tells the provider to
send `sid` instead of `sub`.

The behaviour is specified and model-checked in `specs/oidc_backchannel_logout.fizz`. The checklist above
is the invariant `AcceptedTokenWasGenuine` there: remove a row and the model checker produces exactly the
defect that would get through.

## Traceability

The start, the callback and the session issuance carry the same `X-Request-ID` as any other request.
Successful sign-ins are logged with the provider, the user ID and the tenant ID; tokens, codes and secrets
never are.

## Limitations

- An account created solely through a provider has no local password. Until one is set, the provider is the
  only way in.
- Signing out at the provider requires its discovery document to name an `end_session_endpoint` — which is
  optional in OpenID Connect. Without it, only the local session ends. See
  [signing out at the provider](authentication.md#signing-out-at-the-provider).
- [Back-channel logout](#back-channel-logout) always ends **every** session of the account, not only the one
  the token names. A provider that insists on `backchannel_logout_session_required` is rejected.
