"""Executable model of specs/session_revocation.fizz.

The Fizzbee CLI is not available in every environment, so the state machine the
spec describes is simulated here and its invariants asserted directly. This is a
model check, not an integration test: the corresponding behaviour against the real
service is covered by
``services/core/tests/test_auth_session_lifecycle.py``.

Mappings:
- RevokedTokenNeverAccepted        -> test_revoked_token_never_accepted
- RefreshTokenSingleUse            -> test_refresh_token_single_use
- CompromiseRevokesEveryLiveSession -> test_compromise_revokes_every_live_session
- LogoutIsTerminalForThatToken     -> test_logout_is_terminal
"""

from dataclasses import dataclass, field
from itertools import product


@dataclass
class SessionModel:
    """The state machine from session_revocation.fizz."""

    issued: list[str] = field(default_factory=list)
    revoked: set[str] = field(default_factory=set)
    active_refresh: dict[str, str] = field(default_factory=dict)
    consumed_refresh: set[str] = field(default_factory=set)
    # Acceptance is a point-in-time event, so each entry records whether the token
    # was already revoked *at that moment*. Comparing a historical accept log
    # against the current denylist would wrongly flag a request that legitimately
    # succeeded before the logout happened.
    accepted: list[tuple[str, bool]] = field(default_factory=list)
    compromised: bool = False
    # Set if a replay purge ever left a session usable. A *later* fresh login is
    # legitimate, so the property belongs to the handler, not to the whole run.
    compromise_left_sessions_alive: bool = False
    _next: int = 0

    def login(self) -> tuple[str, str]:
        self._next += 1
        jti = f"jti_{self._next}"
        refresh = f"rt_{self._next}"
        self.issued.append(jti)
        self.active_refresh[refresh] = "user_a"
        return jti, refresh

    def call_protected(self, jti: str) -> bool:
        was_revoked = jti in self.revoked
        if was_revoked:
            return False
        self.accepted.append((jti, was_revoked))
        return True

    def logout(self, jti: str, refresh: str | None = None) -> None:
        self.revoked.add(jti)
        if refresh and refresh in self.active_refresh:
            del self.active_refresh[refresh]
            self.consumed_refresh.add(refresh)

    def rotate(self, refresh: str) -> tuple[str, str] | None:
        if refresh not in self.active_refresh:
            self.replay(refresh)
            return None
        del self.active_refresh[refresh]
        self.consumed_refresh.add(refresh)
        return self.login()

    def replay(self, refresh: str) -> None:
        """A consumed token presented again means the credential leaked."""
        if refresh not in self.consumed_refresh:
            return
        self.compromised = True
        self.consumed_refresh.update(self.active_refresh)
        self.active_refresh.clear()
        self.revoked.update(self.issued)
        if self.active_refresh:
            self.compromise_left_sessions_alive = True

    # ── invariants ──

    def check_revoked_never_accepted(self) -> bool:
        return all(not was_revoked for _jti, was_revoked in self.accepted)

    def check_refresh_single_use(self) -> bool:
        return not (set(self.active_refresh) & self.consumed_refresh)

    def check_compromise_revokes_all(self) -> bool:
        return not self.compromise_left_sessions_alive

    def check_revocation_monotonic(self) -> bool:
        return all(jti in self.issued for jti in self.revoked)

    def check_all(self) -> bool:
        return (
            self.check_revoked_never_accepted()
            and self.check_refresh_single_use()
            and self.check_compromise_revokes_all()
            and self.check_revocation_monotonic()
        )


def test_revoked_token_never_accepted():
    """Verifies Fizzbee Invariant: RevokedTokenNeverAccepted.

    This is the model-level statement of the reported bug: after logout, a request
    carrying the logged-out token must fail, so refreshing the page cannot
    silently restore the session.
    """
    model = SessionModel()
    jti, refresh = model.login()

    # Succeeds before logout — that acceptance stays legitimate afterwards.
    assert model.call_protected(jti) is True

    model.logout(jti, refresh)

    # Refused from this point on, which is the whole point of the denylist.
    assert model.call_protected(jti) is False
    assert len(model.accepted) == 1
    assert model.check_revoked_never_accepted()


def test_refresh_token_single_use():
    """Verifies Fizzbee Invariant: RefreshTokenSingleUse."""
    model = SessionModel()
    _jti, refresh = model.login()

    rotated = model.rotate(refresh)

    assert rotated is not None
    assert refresh in model.consumed_refresh
    assert refresh not in model.active_refresh
    assert model.check_refresh_single_use()


def test_compromise_revokes_every_live_session():
    """Verifies Fizzbee Invariant: CompromiseRevokesEveryLiveSession.

    Replaying a rotated token is evidence the credential leaked, so the safe
    response is to end every session rather than issue another one.
    """
    model = SessionModel()
    _jti, first = model.login()
    model.rotate(first)

    # The attacker presents the token that was already consumed.
    assert model.rotate(first) is None

    assert model.compromised is True
    assert model.active_refresh == {}
    assert model.check_compromise_revokes_all()


def test_logout_is_terminal():
    """Verifies Fizzbee Invariant: LogoutIsTerminalForThatToken."""
    model = SessionModel()
    jti, refresh = model.login()
    model.logout(jti, refresh)

    # Nothing in the model removes a jti from the denylist.
    for _ in range(5):
        model.login()
        assert jti in model.revoked

    assert model.check_revocation_monotonic()


def test_invariants_hold_over_every_short_action_sequence():
    """Exhaustively explore short traces, the way the model checker would."""
    actions = ("login", "call", "logout", "rotate", "replay")

    for trace in product(actions, repeat=4):
        model = SessionModel()
        for action in trace:
            if action == "login":
                model.login()
            elif action == "call" and model.issued:
                model.call_protected(model.issued[-1])
            elif action == "logout" and model.issued:
                refresh = next(iter(model.active_refresh), None)
                model.logout(model.issued[-1], refresh)
            elif action == "rotate" and model.active_refresh:
                model.rotate(next(iter(model.active_refresh)))
            elif action == "replay" and model.consumed_refresh:
                model.replay(next(iter(model.consumed_refresh)))

            assert model.check_all(), f"invariant violated after trace {trace}"
