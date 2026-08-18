# Security Policy

This project stores health data. A vulnerability here is not an inconvenience — it
is somebody's sleep, weight, workouts and location history. Please report anything
you find, including things you are unsure about.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: open the repository's **Security**
tab and choose **Report a vulnerability**. That channel is private until an
advisory is published, so a report never exposes the flaw before there is a fix.

There is deliberately no email address here. This repository is published, and an
address in a tracked file is exactly what it must not carry — see rule 14 in
[AGENTS.md](AGENTS.md).

Helpful in a report, in rough order of usefulness:

- what an attacker gains, and what access they need to start;
- the affected component (`services/core`, `services/api-gateway`, an importer, the
  dashboard) and version or commit;
- the smallest sequence of requests or steps that shows it;
- whether tenant isolation is crossed — see below.

Expect an acknowledgement within a few days. This is a single-maintainer project,
so a fix is best effort rather than a guaranteed window; you will be told which it
is rather than left waiting. If you would like credit in the advisory, say so.

## Please do not

- test against a deployment that is not yours;
- run denial-of-service or load tests against any hosted instance;
- open a public issue for something exploitable.

## What we consider a vulnerability

**Anything crossing tenant isolation is the most serious class.** Every query is
supposed to filter by `tenant_id` and every endpoint is supposed to derive it from
the validated token, never from a client-supplied header. A path that reads or
writes another tenant's rows is a top-severity report even if it needs an
authenticated account.

Also in scope:

- authentication or session handling that lets one user act as another;
- connector credentials recoverable in plaintext — they are encrypted at rest with
  Fernet AES-256 and must never appear in logs or NATS payloads;
- anything that lets a request reach the database other than through
  `services/core`;
- the platform-admin gate, or privilege escalation between roles;
- injection, SSRF or path traversal reachable through the Gateway or an importer.

## What is not a vulnerability

**The development secrets printed in this repository are published on purpose.**
`JWT_SECRET`, `ENCRYPTION_KEY` and `INTERNAL_SERVICE_SECRET` have defaults so a
local checkout needs no configuration, and they are guarded on both sides: the
production compose file uses `${VAR:?…}` so a missing variable aborts the deploy,
and Core, the Gateway and the Analysis service refuse to start when `ENVIRONMENT`
is production-like and any secret still matches a published default. A report that
these values are readable here is a report that the design is working.

Also generally out of scope:

- a self-hosted deployment that set its own secrets badly, or exposed a service
  that is meant to stay internal;
- missing hardening headers with no demonstrated impact;
- output from an automated scanner with no reproduction;
- vulnerabilities in a third-party dependency with no path to exploiting them
  here — report those upstream, though a note here is welcome if this project's
  usage is what makes them reachable.

## Supported versions

The latest release and the `main` branch. Older tags do not receive fixes; this
project is young enough that upgrading is the remedy.

## Handling your data

A report is treated as confidential. If a fix changes what a deployment must tell
its users, the advisory says so — an operator's privacy policy is their own
responsibility, and this project's job is to give them the facts in time.
