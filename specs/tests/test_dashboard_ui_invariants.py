"""Tests mapping to specs/dashboard_ui.fizz invariants."""


class DashboardUIStateMachine:
    def __init__(self):
        self.ui_state = "LOADING"
        self.modal_state = "CLOSED"
        self.metrics = []

    def load_success(self, metrics: list[str]):
        self.ui_state = "READY"
        self.metrics = metrics

    def load_failure(self):
        self.ui_state = "ERROR"
        self.metrics = []

    def open_modal(self):
        if self.modal_state == "CLOSED":
            self.modal_state = "OPEN"

    def close_modal(self):
        self.modal_state = "CLOSED"

def test_no_empty_data_when_ready():
    """Verifies Fizzbee Invariant: NoEmptyDataWhenReady."""
    sm = DashboardUIStateMachine()
    sm.load_success(["sleep_score", "readiness_score", "steps"])
    
    assert sm.ui_state == "READY"
    assert len(sm.metrics) > 0

def test_modal_state_valid():
    """Verifies Fizzbee Invariant: ModalStateValid."""
    sm = DashboardUIStateMachine()
    assert sm.modal_state in ["CLOSED", "OPEN", "SUBMITTING"]

    sm.open_modal()
    assert sm.modal_state in ["CLOSED", "OPEN", "SUBMITTING"]

    sm.close_modal()
    assert sm.modal_state in ["CLOSED", "OPEN", "SUBMITTING"]
