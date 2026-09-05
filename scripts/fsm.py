from enum import Enum, auto

class State(Enum):
    OPEN = auto()
    HANDOFF_PENDING = auto()
    EXECUTION_ACTIVE = auto()
    REVIEWING = auto()
    RECOVERY_REQUIRED = auto()
    CLOSED = auto()

class Event(Enum):
    STOP_REQUESTED = auto()
    WORK_PREPARED = auto()
    PRIMARY_TOOL_DENIED = auto()
    HANDOFF_ACCEPTED = auto()
    HANDOFF_FAILED = auto()
    WORK_TERMINATED_OK = auto()
    WORK_TERMINATED_ERROR = auto()
    WORK_TIMED_OUT = auto()

class TransitionError(Exception):
    pass

class FSM:
    def __init__(self, initial_state=State.OPEN):
        self.state = initial_state

    def transition(self, event, context=None):
        if self.state == State.OPEN:
            if event == Event.STOP_REQUESTED:
                if context and not context.get("active_work"):
                    self.state = State.CLOSED
                    return "Append TURN_CLOSED"
            elif event == Event.WORK_PREPARED:
                if context and context.get("tool") == "invoke":
                    self.state = State.HANDOFF_PENDING
                    return "None"
            elif event == Event.PRIMARY_TOOL_DENIED:
                self.state = State.RECOVERY_REQUIRED
                return "Write marker"

        elif self.state == State.HANDOFF_PENDING:
            if event == Event.HANDOFF_ACCEPTED:
                self.state = State.EXECUTION_ACTIVE
                return "None"
            elif event == Event.HANDOFF_FAILED:
                self.state = State.RECOVERY_REQUIRED
                return "Write marker"

        elif self.state == State.EXECUTION_ACTIVE:
            if event == Event.WORK_TERMINATED_OK:
                if context and context.get("all_work_terminal") and not context.get("failures"):
                    self.state = State.REVIEWING
                    return "None"
            elif event == Event.WORK_TERMINATED_ERROR:
                self.state = State.RECOVERY_REQUIRED
                return "Write marker"
            elif event == Event.WORK_TIMED_OUT:
                self.state = State.RECOVERY_REQUIRED
                return "Write marker"

        elif self.state == State.REVIEWING:
            if event == Event.WORK_PREPARED:
                self.state = State.HANDOFF_PENDING
                return "None"
            elif event == Event.STOP_REQUESTED:
                self.state = State.CLOSED
                return "Append TURN_CLOSED"

        elif self.state == State.RECOVERY_REQUIRED:
            if event == Event.WORK_PREPARED:
                if context and context.get("valid_handoff"):
                    self.state = State.HANDOFF_PENDING
                    return "Clear marker"
            elif event == Event.STOP_REQUESTED:
                if context and context.get("retries_exhausted"):
                    self.state = State.CLOSED
                    return "None"

        return "Invalid transition"
