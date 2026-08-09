# Licensing

This page records which licence this project is under, which third-party software it
redistributes, and which obligations follow from that. It is a stocktake, **not legal advice** —
the places where that distinction matters are marked as such below.

## Our own code: AGPL-3.0

`LICENSE` in the repository root: the GNU Affero General Public License, version 3, in the FSF's
wording, with a copyright line in front of it. So that this is not only stated there:

- all thirteen `pyproject.toml` files and the dashboard's `package.json` declare
  `license = "AGPL-3.0-only"`,
- all thirteen images carry `org.opencontainers.image.licenses=AGPL-3.0-only` as an OCI label,
- the deployment bundle of every release contains `LICENSE`.

The project was MIT licensed before. The change was possible because at that point **nobody** had
received a copy: the repository was private, the GHCR packages were private, and the single release
`v0.1.0` was deleted. MIT is a grant of rights to recipients — with no recipients there is nothing
that binds. The commit history has exactly one author, so no third party's consent was needed
either.

!!! warning "§13 is an obligation for the operator, not only for a redistributor"
    Whoever makes the software usable over a network must offer its users the **corresponding
    source of the running version**. A link to the default branch does not do that — the deployed
    state and the branch tip diverge at the next merge.

    So the dashboard image gets the version and the commit as build arguments (`SOURCE_VERSION`,
    `SOURCE_COMMIT`, set by the release workflow), and the footer links to exactly that state. A
    local build without those arguments links the repository. Anyone who builds the image
    themselves and operates it publicly has to set the arguments, or fill the link correctly some
    other way.

The AGPL permits self-hosting and modification without restriction. Whoever runs the service for
other people and changes the code to do so has to publish those changes. For the dependencies this
is uncritical: all of them are MIT, BSD-2-Clause, ISC or Apache-2.0, and Apache-2.0 is compatible
with GPLv3 (with v2 it would not be).

## Redistributed third-party software

A container image is a copy in the sense the licences mean. MIT, BSD-2-Clause and ISC all require
their copyright notice to accompany a copy.

**Python images** (Core, Analysis, Gateway, eight importers): the dependencies are installed into
the venv, which the Dockerfiles copy into the image as a whole — together with the licence files in
the `*.dist-info` directories. Core's venv contains 42 of them.

**Dashboard image**: `apps/dashboard/THIRD-PARTY-NOTICES.txt`, produced by
`scripts/generate-notices.ts` from the production dependency tree (22 packages), plus the two
self-hosted webfonts. The file is regenerated in the builder and copied into the runtime image; CI
checks with `bun run notices --check` that the committed version matches the dependency tree.

!!! note "Why that needs a file of its own"
    The image used to ship the complete `node_modules` — and with it, incidentally, 271 licence
    files. Moving to Next's standalone output shrank the image from 636 MB to 155 MB, because only
    the JavaScript actually reached is traced in — and licence files are not part of that. The
    obligation stayed, the notice disappeared. Hence deliberately now, rather than by accident.

**Fonts**: `next/font/google` downloads Outfit and JetBrains Mono at build time and puts eleven
`.woff2` files into the bundle — so the dashboard self-hosts them and redistributes them. Both are
under OFL-1.1, which requires the copyright notice and the licence text to travel with a copy. The
texts are under `apps/dashboard/licenses/` and are taken unchanged from the upstream projects.

**Map tiles**: the attribution for OpenStreetMap and CARTO is set on the `TileLayer` and is
rendered in the map — that is the ODbL obligation.

## Components with conditions worth knowing about

| Component | Licence | What that means |
| --- | --- | --- |
| TimescaleDB | Apache-2 **and** TSL | Only `create_hypertable` is used, which is in the Apache-2 part. The TSL features (compression, continuous aggregates, retention policies) are **not** in use. |
| PostGIS | GPL-2.0 | Runs as its own PostgreSQL process and is reached over SQL — separate programs, no linking. With AGPL-3.0, GPL-2.0-only is only compatible that way, not in the same process. |
| NATS, cloudflared, gRPC, asyncpg | Apache-2.0 | Require any `NOTICE` files to be passed on — satisfied, because the images contain the packages along with their licence files. |
| Traefik, Material for MkDocs, Bun, Next.js, React | MIT | The notice has to travel along; see above. |
| Leaflet | BSD-2-Clause | Like MIT, with an explicit clause — it is in `THIRD-PARTY-NOTICES.txt`. |
| Yazio API | no licence, private API | See below. |

## If this becomes a service for other people

For self-hosting nothing changes. Whoever **offers the platform to others as a service** should have
settled these six points first. The first two are the riskiest in practice, and neither of them is a
licensing question in the narrow sense.

1. **Yazio.** The importer talks to `yzapi.yazio.com` with the Yazio app's OAuth client credentials
   — they are in `services/core/src/core/config.py`, because they are shipped inside that app. For
   exporting your own data this is a grey area that bothers nobody in practice. For a paid product it
   is a different conversation: somebody else's app credentials against an undocumented API is the
   most likely reason to be cut off. **This is where a lawyer belongs, or an official clearance.**
2. **Health data.** These are special categories under Art. 9 GDPR. For other people's users that
   means at least: explicit consent, very probably a data protection impact assessment under Art. 35,
   processor agreements with every subprocessor, a record of processing activities, and workable paths
   for access, export and deletion. Tenant separation and encrypted connector credentials are half of
   it; the other half is paperwork. **That too is a lawyer's subject, not a code subject.**
3. **Our own licence** is decided: AGPL-3.0. Self-hosting stays free for anyone, but whoever runs the
   service and changes the code to do so has to publish the changes. The price of that is §13, see
   above — the obligation applies to running it yourself as well.
4. **WHOOP.** An official developer API (`api.prod.whoop.com/developer`) — use falls under their
   developer terms, and commercial use there normally needs a clearance.
5. **Map tiles.** Under OSM's Tile Usage Policy, `tile.openstreetmap.org` is not intended for
   commercial or high-traffic use. That is a configuration question, not a rebuild: switch the
   provider with `NEXT_PUBLIC_MAP_TILE_PROVIDER` and adjust `MAP_TILE_HOSTS` in the CSP.
6. **Weather.** The importer gets its host from the connector configuration; the project does not fix
   a provider. If you use Open-Meteo: the free access is intended for non-commercial use, and there is
   a paid tier for commercial use.

## Checking

```bash
task check:private                        # no personal data in the repository
bun run --cwd apps/dashboard notices      # regenerate the notices
bun run --cwd apps/dashboard notices --check   # also runs in CI
```
