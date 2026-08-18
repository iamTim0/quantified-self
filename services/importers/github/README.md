# GitHub Importer

Reads the authenticated account's own contribution activity and publishes it to
`qs.ingest.github`.

Full documentation: [docs/importers/github.md](../../../docs/importers/github.md).

## What it emits

Daily, for every day in the window including the empty ones: `code_commits`,
`code_lines_added`, `code_lines_removed`, `code_repositories_touched`,
`code_pull_requests_opened`, `code_pull_requests_merged`, `code_reviews_submitted`,
`code_issues_opened`.

Once per run: `code_contribution_streak`, `code_followers`, `code_stars_received` —
all `LAST` metrics, so writing one per day would fabricate a history.

Per repository, on days with commits: `github_<owner>_<repo>_commits`, under the
registered dynamic namespace.

## Credentials

A fine-grained personal access token, entered in the dashboard and stored encrypted
in Core. This importer holds no credential of its own (rule 8): it fetches one per
run from `GET /api/v1/internal/data/sources/{source_ref}/token`.

## Running it

```bash
task run:importer:github
```

Requires NATS and Core. Health on `http://127.0.0.1:8014/health` — broker
connectivity only, never GitHub reachability and never the token.

## Tests

```bash
uv run --directory services/importers/github --with pytest --with pytest-asyncio pytest tests
```
