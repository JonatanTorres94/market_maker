from src.db.database import Database
from src.domain.models import CycleSnapshot, InventoryPnL, OrderPlacementRecord


class DbTradeJournal:
    def __init__(self, db: Database, session_id: str):
        self._db = db
        self._session_id = session_id

    def record_cycle(self, snapshot: CycleSnapshot) -> None:
        self._db.insert_cycle(self._session_id, snapshot)

    def record_order(self, order: OrderPlacementRecord) -> None:
        self._db.insert_order(self._session_id, order)

    def record_equity(self, equity: InventoryPnL) -> None:
        self._db.insert_equity(self._session_id, equity)
