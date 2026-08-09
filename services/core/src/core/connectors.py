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


def credential_is_optional(source_type: str) -> bool:
    """Whether this connector may exist without a stored provider credential.

    One definition rather than three. The same predicate decides whether a
    connector may be *saved* without a credential, whether it is *listed*, and
    whether its token endpoint answers — and when those three drifted apart, a
    connector could be created and then never seen again.
    """
    return source_type in CREDENTIAL_OPTIONAL_SOURCE_TYPES


def is_scheduled(source_type: str) -> bool:
    """Whether the scheduler should ever plan a sync for this connector.

    False for push connectors: nothing subscribes to their task subject, so a
    planned run is a row that can only ever expire.
    """
    return source_type not in PUSH_SOURCE_TYPES
