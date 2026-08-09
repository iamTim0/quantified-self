# Tenant-bound API keys

## What they are for

Some data sources send data to the platform actively instead of being polled — currently
**Apple Health** (Health Auto Export) and **Streak**. Those services authenticate with an API key you
create in the dashboard.

## One header is enough

The external service sends nothing but:

```http
POST /api/v1/ingest/apple-health
Authorization: Bearer <api-key>
Content-Type: application/json
```

A separate `X-Tenant-ID` header is **not** required, and is not accepted either if it names a
different tenant from the key's. The tenant is determined server-side from the key.

For compatibility, `X-Api-Key: <api-key>` is still accepted as well, because existing Health Auto
Export and Streak configurations use that header.

## How the mapping works

1. The importer computes the SHA-256 hash of the presented key locally.
2. It asks Core about the **hash** — the key itself never leaves the edge service.
3. Core looks the hash up, checks the status, the expiry and the permitted data source, and returns
   the matching `tenant_id`.
4. Every event derived from it carries that `tenant_id`, a deterministic `idempotency_key` and the
   `X-Request-ID`.

If any step fails — unknown key, revoked key, expired key, a key for a different data source, or Core
unreachable — the request is rejected. There is no path on which unauthenticated data is accepted.

## What is stored

| Field | Purpose |
| --- | --- |
| `key_prefix` | the first 12 characters, for recognition in the UI and in logs |
| `key_hash` | SHA-256 of the key; the only thing the tenant is derived from |
| `tenant_id` | the owner |
| `source_type` | the permitted data source |
| `scopes` | permissions, `ingest` only by default |
| `status` | `active` or `revoked` |
| `expires_at` | optional expiry |
| `last_used_at` | last successful use |
| `created_at`, `created_by_user_id` | provenance |

The full key is shown **once**, when it is created, and never again — not in the list, and not in
logs, error messages or events.

## Rotation without an interruption

Rotating creates a second key while the old one stays active:

1. `POST /api/v1/data/api-keys/{id}/rotate` → the new key is shown once.
2. Switch the external service to the new key.
3. `POST /api/v1/data/api-keys/{id}/revoke` for the old key.

Several active keys per tenant are explicitly intended. Only the revocation ends the old key's
validity — immediately, and with no cache in the way.

## API

| Method | Path | Role | Purpose |
| --- | --- | --- | --- |
| `POST` | `/api/v1/data/api-keys` | owner, admin | Create a key (shows it once) |
| `GET` | `/api/v1/data/api-keys` | everyone | List the keys (without key material) |
| `POST` | `/api/v1/data/api-keys/{id}/rotate` | owner, admin | Create a successor |
| `POST` | `/api/v1/data/api-keys/{id}/revoke` | owner, admin | Invalidate immediately |

```http
POST /api/v1/data/api-keys
Authorization: Bearer <jwt>

{ "name": "iPhone Health Auto Export", "source_type": "apple_health", "expires_in_days": 365 }
```

## Security properties

- A key for `apple_health` does not work on the Streak endpoint (`403`).
- Another tenant's key is invisible and cannot be revoked (`404`).
- A contradictory `X-Tenant-ID` header produces a `403`, not a silent correction.
- Missing or invalid key: `401`. Missing permission: `403`.

## Limits

- Keys are currently only intended for push sources (`apple_health`, `streak`).
- There is not yet an automatic expiry reminder or any usage reporting beyond `last_used_at`.
