from src.db.database import Database
from src.domain.execution import Execution


class DbExecutionJournal:
    def __init__(self, db: Database, session_id: str):
        self._db = db
        self._session_id = session_id

    def record_execution(self, execution: Execution) -> None:
        self._db.insert_execution(self._session_id, execution)
