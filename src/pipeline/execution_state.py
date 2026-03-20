from dataclasses import dataclass
from domain.execution import Execution
from decimal import Decimal


@dataclass
class ExecutionState:
    execution: Execution

    is_reconciled: bool = False
    is_fee_resolved: bool = False
    is_ordered: bool = False

    commission_in_quote: Decimal | None = None