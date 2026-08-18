# Contributing

Thanks for looking. This is a multi-tenant microservice platform, and most of what
makes a change acceptable here is architectural rather than stylistic.

## Read this first

[AGENTS.md](AGENTS.md) is the binding rulebook — twenty numbered rules, each of
which exists because breaking it cost something. It is not long, and skimming the
"Absolute Rules" section will save you a rejected pull request. The rules that get
broken most often:

- **Only `services/core/` touches the database.** No other service may import
  SQLAlchemy or asyncpg. Analysis reads through Core's gRPC API; importers publish
  to NATS and never query anything.
- **Every query filters by `tenant_id`.** No exceptions.
- **Metric names come from the registry** in
  `packages/shared-schemas/src/shared_schemas/metrics.py`. A name never carries its
  unit or its source. After changing the registry, run `task metrics:generate`.
- **Migrations need a working `downgrade()`.** An empty one is not a rollback.
- **Every migration and importer change updates the docs** under `docs/`.
- **One language: English.** Code, comments, commit messages, log lines. The four
  content exceptions are listed in rule 16; a German comment is a defect.
- **No user-visible literal in a dashboard component.** Strings go through
  `t("area.thing")` and exist in both catalogues.
- **Nothing personal in a tracked file** — no real email address, deployment
  hostname, absolute local path or personal data. Rule 14 lists what that means and
  `.agents/scripts/check_private_info.py` enforces it.

## Getting set up

Python services use [uv](https://docs.astral.sh/uv/), the dashboard uses
[Bun](https://bun.sh), and everything is driven through
[Task](https://taskfile.dev):

```bash
cp .env.example .env        # dev defaults work as they are
task dev                    # bring the stack up
```

The defaults in `.env.example` are loopback addresses and published development
secrets, so a fresh checkout runs with no configuration. Production refuses to
start on them, which is the point.

## Before you open a pull request

```bash
task lint          # ruff across the Python services
task test:all      # the full suite
```

The dashboard additionally needs `bun tsc --noEmit` to pass, which is what keeps
the two message catalogues in step: a key missing from `catalog-de.ts` is a type
error, not an empty element at runtime.

If you changed anything under `services/`, `packages/` or `specs/`, update the
matching page under `docs/`. The `Stop` hook checks this and will tell you.

## Tests

- Every service has its own `tests/` directory.
- **Tests create their own fixtures.** Never assume a pre-existing tenant, user or
  row, and clean up afterwards. A test that depends on a seeded database passes on
  your machine and nowhere else.
- Unit tests mock NATS, gRPC and every external API.
- Where a test verifies a formal invariant, name it in the docstring:
  `"""Verifies Fizzbee Invariant: NoDuplicateRecords"""`.
- Assert on a `code`, a status or a structure — not on a fragment of prose that the
  next wording change would silently defeat.

## Commits

Conventional commits, as the history uses them:

```
fix(dashboard): stop the quality page contradicting itself
feat(core): add metric quarantine
```

Say **why** in the body when the reason is not obvious from the diff. Commit
messages are treated as documentation here; several rules in `AGENTS.md` cite the
incident that produced them, and that history came from commit messages.

## Adding an importer

There is a checklist in [AGENTS.md](AGENTS.md#when-adding-a-new-importer) — ten
steps, including the three places a new image has to be registered and the
healthcheck contract. Follow it in order; step 7 is the one people miss, and a
Dockerfile missing from `tools/build_images.py` is an image that is never built.

## Specifications

New distributed coordination needs a Fizzbee specification in `specs/` before the
implementation. Existing patterns do not — if you are not sure which yours is, open
an issue and ask.

## Licence

Contributions are made under [AGPL-3.0-only](LICENSE). By opening a pull request
you agree that your contribution ships under it.
