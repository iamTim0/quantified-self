# Quantified Self documentation

This documentation is a separate, static site for operators and users. It is built with
**Material for MkDocs**, which combines Markdown as the maintenance format with search,
navigation and a lean Python build. MkDocs describes itself as a static generator for
project documentation written in Markdown; Material for MkDocs adds a searchable,
responsive interface on top.

## Running it locally

```bash
task docs:serve
```

In the Docker setup the documentation is routed through Traefik under `/docs`, which keeps
it deliberately separate from the product UI.

## Architectural principles

- Importers are stateless and publish nothing but tenant-scoped NATS events on `qs.ingest.<source_type>`.
- Credentials are fetched from Core at run time and never stored in an importer.
- Every event carries `tenant_id`, `source_id`, `metric_type`, `timestamp` and a deterministic `idempotency_key`.
- Core stays the only service with database access; the Analysis service reads over gRPC.
- The MCP surface is read-only and sessionless: every request is authenticated on its own, and the
  tenant comes from the token rather than from a tool argument, so no conversation can select one.
- Distributed interactions are specified in `specs/` and model-checked before they are implemented.

## Where to start

| Page | Contents |
| --- | --- |
| [Architecture](architecture.md) | Services, data flow, idempotency, tenant isolation, scheduler |
| [Release and deployment](deployment.md) | Publishing images, standing up the stack, updating, rolling back |
| [Operations](operations.md) | Required variables, key rotation, monitoring, backup |
| [Authentication](features/authentication.md) | Sessions, cookies, logout, route guard |
| [External sign-in (OIDC)](features/oidc.md) | Provider administration, account linking, back-channel logout |
| [API keys](features/api-keys.md) | Tenant-bound inbound keys |
| [Stateless MCP analytics](features/mcp.md) | The read-only tool surface, its bounds, and what publishing it would require |
| [AI chat](features/ai-chat.md) | The `/chat` page, the Codex adapter, and why a tool call re-authenticates |
| [Licensing](licensing.md) | Our own licence, redistributed third-party software, what a network service changes |
| [Troubleshooting](troubleshooting.md) | Common failure modes and what they mean |

!!! danger "Before the first production deployment"
    `JWT_SECRET`, `INTERNAL_SERVICE_SECRET` and `ENCRYPTION_KEY` have defaults that are
    printed in this repository. The production stack no longer starts on them, and
    `ENCRYPTION_KEY` requires a re-encryption pass **before** it is changed. See
    [Operations](operations.md#required-configuration).

## Legal

The legal texts are maintained inside the application itself, so that they always match
the running version:

- [Privacy policy](/legal/datenschutz)
- [Imprint](/legal/impressum)

Both are templates with placeholders and must be reviewed by a qualified party before any
production use. Both are bilingual, and the German wording is the binding one.

## External references

- [MkDocs](https://www.mkdocs.org/) for Markdown-based project documentation.
- [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) for search, navigation and responsive design.
