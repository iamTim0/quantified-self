"""What kind of thing each connector type is.

One module rather than a constant in `main.py`, because the scheduler needs the
same answers and `main` imports *it* — and because the three questions below used
to be answered in three different places that could disagree. They did: the
scheduler had no notion of a push connector at all, so it planned syncs for Apple
Health onto `qs.task.sync.apple_health`, a subject nothing subscribes to. Every
push connector therefore accumulated `SyncRun` rows stuck in `queued` until they
aged out six hours later, forever.
"""

# Connectors that receive pushed data. They authenticate inbound requests with
# tenant-bound API keys (see the api_keys table), so they hold no provider
# credential of their own and must be configurable without one.
PUSH_SOURCE_TYPES = frozenset({"apple_health", "streak"})

# Connectors that never need a provider credential, whatever they are configured
# with. Weather is here because its default provider, Open-Meteo, issues no keys
# at all: demanding one made the connector impossible to set up from the
# dashboard, and `GET /sources` then dropped it from the list as "unconfigured",
# so it could not even be repaired afterwards.
# Calendar is here unconditionally: a calendar is an ICS feed, and the only
# credential such a feed can carry is inside its own URL. The importer's bearer
# mode was removed because it never worked -- it added an `Authorization` header
# and then still demanded an ICS body in reply.
CREDENTIAL_OPTIONAL_SOURCE_TYPES = PUSH_SOURCE_TYPES | frozenset({"weather", "calendar"})

# Providers that will hand a user their own history as a file — Apple Health's
# `export.zip` from the Health app, Whoop's emailed ZIP of CSVs. Both need no API
# application, no OAuth and no developer account, which for a one-off is the whole
# difference between having your data and not.
FILE_IMPORT_SOURCE_TYPES = frozenset({"apple_health", "whoop"})

# `config["import_mode"]` for a connector that is fed by uploads alone. The other
# value is absent: a connector configured the ordinary way carries no import_mode,
# because "how do I normally get data" is what the source type already answers.
IMPORT_MODE_FILE = "file"


def supports_file_import(source_type: str) -> bool:
    """Whether an export file can be uploaded for this connector type at all."""
    return source_type in FILE_IMPORT_SOURCE_TYPES


def is_file_import(source_type: str, config: dict | None = None) -> bool:
    """Whether this particular connector is fed by uploaded files only.

    A file-import connector is a real row in `data_sources` — it has to be, because
    its id is the second component of every idempotency key its uploads derive, and
    that is what makes uploading the same export twice a no-op instead of a second
    copy of a year of history.
    """
    return supports_file_import(source_type) and (config or {}).get("import_mode") == IMPORT_MODE_FILE


def credential_is_optional(source_type: str, config: dict | None = None) -> bool:
    """Whether this connector may exist without a stored provider credential.

    One definition rather than three. The same predicate decides whether a
    connector may be *saved* without a credential, whether it is *listed*, and
    whether its token endpoint answers — and when those three drifted apart, a
    connector could be created and then never seen again.
    """
    return source_type in CREDENTIAL_OPTIONAL_SOURCE_TYPES or is_file_import(source_type, config)


def is_scheduled(source_type: str, config: dict | None = None) -> bool:
    """Whether the scheduler should ever plan a sync for this connector.

    False for push connectors: nothing subscribes to their task subject, so a
    planned run is a row that can only ever expire. False for file imports too, and
    for the same reason — the data arrives when somebody uploads it, so a poll has
    nothing to poll.
    """
    return source_type not in PUSH_SOURCE_TYPES and not is_file_import(source_type, config)
