## What this changes

<!-- What behaviour is different afterwards, and why. Link an issue if there is one. -->

## Why

<!-- The reason, if the diff does not make it obvious. This becomes the commit
     message body, and commit messages are documentation in this repository. -->

## Checklist

- [ ] `task lint` and `task test:all` pass
- [ ] Tests create their own fixtures and assume no pre-existing database state
- [ ] Docs under `docs/` updated if this touches `services/`, `packages/` or `specs/`
- [ ] English only — code, comments, log lines, commit message (rule 16)

If it applies to this change:

- [ ] Every database query filters by `tenant_id` (rule 2)
- [ ] No service other than `services/core/` touches the database (rule 1)
- [ ] Any new `metric_type` is in the registry, and `task metrics:generate` was run (rule 15)
- [ ] Any migration has a working `downgrade()` (rule 7)
- [ ] Every provider field is stored, carried in `metadata`, or named in the field report (rule 19)
- [ ] New dashboard strings go through `t("area.thing")` and exist in **both** catalogues
- [ ] A new long-running service has a Dockerfile `HEALTHCHECK` and a production Compose `healthcheck:` (rule 20)
- [ ] A new image is registered in `infra/docker-compose.yml`, `docker-compose.prod.yml` **and** `tools/build_images.py`
- [ ] Nothing personal in a tracked file — no real email, hostname, absolute path or personal data (rule 14)
