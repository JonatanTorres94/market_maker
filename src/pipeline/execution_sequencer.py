# src/pipeline/execution_sequencer.py

import heapq
from typing import Dict, Tuple, List
from dataclasses import dataclass, field

from decimal import Decimal


@dataclass(order=True)
class PrioritizedExecution:
    sort_index: Tuple[int, int]  # (timestamp, trade_id)
    execution: object = field(compare=False)


class ExecutionSequencer:

    def __init__(self):
        # heap por (exchange, account, symbol)
        self.heaps: Dict[Tuple[str, str, str], List[PrioritizedExecution]] = {}

        # último trade_id aplicado por stream
        self.last_trade_id: Dict[Tuple[str, str, str], int] = {}

    def _key(self, e):
        return (e.exchange, e.account, e.symbol)

    def add(self, execution):
        key = self._key(execution)

        if key not in self.heaps:
            self.heaps[key] = []

        heapq.heappush(
            self.heaps[key],
            PrioritizedExecution(
                (execution.timestamp, execution.trade_id),
                execution
            )
        )

    def get_next_batch(self) -> List:
        """
        Devuelve executions ordenados y SIN gaps.
        Si detecta gap → corta.
        """
        output = []

        for key, heap in self.heaps.items():

            last_id = self.last_trade_id.get(key)

            while heap:
                candidate = heap[0].execution  # peek

                # Primer elemento (bootstrap)
                if last_id is None:
                    heapq.heappop(heap)
                    candidate.is_ordered = True

                    self.last_trade_id[key] = candidate.trade_id
                    last_id = candidate.trade_id

                    output.append(candidate)
                    continue

                # GAP DETECTION
                expected = last_id + 1

                if candidate.trade_id != expected:
                    # gap detectado → NO procesar más
                    break

                # OK → consumir
                heapq.heappop(heap)
                candidate.is_ordered = True

                self.last_trade_id[key] = candidate.trade_id
                last_id = candidate.trade_id

                output.append(candidate)

        return output