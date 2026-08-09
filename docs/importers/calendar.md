# Calendar importer

## Purpose

The calendar importer reads an **ICS/iCalendar feed** and turns it into time series for
appointments, meeting duration and busy time.

## There is no API key

A calendar is an ICS feed, and the only credential such a feed can carry is inside its own
URL. There is no API key field, for any provider — Outlook/Microsoft 365, Google Calendar,
iCloud and Nextcloud all publish ICS.

The importer distinguishes three kinds of access and detects them automatically from your
configuration:

| Mode | When | Credentials |
| --- | --- | --- |
| `public_ics` | A publicly shared feed URL | none |
| `private_ics` | A private, "secret" feed address (a long token in the path or as a query parameter) | the URL itself is the secret |
| `basic_auth` | A CalDAV server with a username and password | username + password |

You can also set the mode explicitly with `auth_mode` in the connector configuration, if the
automatic detection gets it wrong.

A fourth mode, `api_key`, used to exist and has been removed. It never did what its name
suggested: it added an `Authorization: Bearer` header and then still required an ICS body in
reply, so a JSON REST calendar was never actually supported. All it achieved in practice was
to demand a credential for any feed whose path did not end in `.ics` — which made perfectly
ordinary feeds impossible to add.

## Several calendars

The connector can be configured more than once. Give each instance a **name** — "Work",
"Family" — and they are imported, scheduled and shown independently. Each keeps its own data:
the connector's id is part of every idempotency key, so two calendars never merge into one
series and one importing does not hold up the other.

!!! warning "A private feed URL is a credential"
    A private ICS address gives anyone who knows it full access to your calendar. It is
    therefore stored encrypted (Fernet AES-256) and never written to logs, error messages or API
    responses — those only ever show `https://host/…`.

## Setup

1. Create an iCalendar/ICS subscription link in your calendar product.
2. Open the **Calendar** connector in the dashboard.
3. Give it a name, and enter the ICS URL in the **Calendar feed URL** field.
4. Optionally set the poll interval and the period, then start the sync.

### Where to get the link

- **Google Calendar**: calendar settings → "Secret address in iCal format".
- **Apple/iCloud**: share the calendar → copy the public calendar link (replace `webcal://` with `https://`).
- **Outlook/Microsoft 365**: publish the calendar → copy the ICS link.
- **Nextcloud**: share the calendar → copy the subscription link.

## Recurrence and time zones

- `RRULE`, `EXDATE` and `RECURRENCE-ID` are evaluated. A weekly series produces one data point
  per occurrence, not one for the whole series.
- A moved single occurrence of a series (`RECURRENCE-ID`) replaces the series occurrence.
- `DTSTART;TZID=` and `VTIMEZONE` are resolved and normalized to UTC.
- All-day events (`VALUE=DATE`) and events without a time zone are anchored in the configured
  display time zone (`timezone` in the connector configuration, `UTC` by default). "Was I busy on
  Tuesday?" is a local question.
- Cancelled events (`STATUS:CANCELLED`) and entries marked as free (`TRANSP:TRANSPARENT`) are
  imported, but do not count as busy time.

## Metrics

| Metric | Meaning |
| --- | --- |
| `calendar_event_count` | number of events per day (`count`) |
| `calendar_busy_duration` | total busy time per day (`min`) |
| `calendar_meeting_duration` | duration of a single event (`min`) |

`calendar_busy_hours` is gone. It carried the same number as `calendar_busy_minutes`, only in a
different unit — purely because the unit was part of the name. The correlation analysis duly
reported the two as perfectly correlated series. The unit now lives in the registry, one metric
is enough, and presenting it in hours is the interface's business.

Per-event data points are identified by their UID and, where present, `RECURRENCE-ID`. Two
different events in the same minute therefore do not collide.

## Retrieving the data

```http
GET /api/v1/data/metrics?metric_type=calendar_busy_duration&start_time=<iso>&end_time=<iso>
Authorization: Bearer <jwt>
```

The tenant is derived from the token; a separate `X-Tenant-ID` header is not required.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| "Calendar URL returned an HTML page" | The feed wants a sign-in, or the secret address was withdrawn | Create a new feed URL in the calendar product |
| "Calendar feed not found (404)" | The address was revoked, or the calendar was deleted | Create the link again |
| "not iCalendar data" | The URL points at a web view instead of at the feed | Use the ICS link, not the calendar's web link |
| No events imported | Every event lies outside the import period | Widen the period in the import dialog |

## Limitations

- Pure CalDAV discovery (`PROPFIND`) is not supported, only direct feed URLs.
- A feed with more than 10,000 events in the period is truncated; that is logged.
- Attendee lists, descriptions and attachments are not imported.

## References

- [iCalendar.org](https://icalendar.org/) for standard resources and validators.
- [RFC 5545 / iCalendar overview](https://en.wikipedia.org/wiki/ICalendar) as an introduction to
  fields like `VEVENT`, `DTSTART` and `DTEND`.

The full definition of every metric — its unit, its aggregation and the former names that still
point at it — is in [Metrics](../metrics.md).
