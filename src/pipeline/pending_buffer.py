from typing import Dict, List
from pipeline.execution_state import ExecutionState


class PendingExecutionBuffer:

    def __init__(self):
        self.buffer: Dict[tuple, ExecutionState] = {}

    def add(self, execution):
        state = ExecutionState(execution=execution)
        self.buffer[state.key] = state

    def get_all(self) -> List[ExecutionState]:
        return list(self.buffer.values())

    def get_ready(self) -> List[ExecutionState]:
        return [
            s for s in self.buffer.values()
            if s.is_reconciled and s.is_fee_resolved
        ]

    def remove(self, key):
        if key in self.buffer:
            del self.buffer[key]