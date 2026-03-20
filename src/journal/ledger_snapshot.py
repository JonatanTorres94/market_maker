import json


class LedgerSnapshot:

    def __init__(self, ledger):
        self.ledger = ledger

    def dump(self, path: str):
        data = {}

        for (exchange, account, symbol), state in self.ledger.states.items():
            key = f"{exchange}:{account}:{symbol}"

            data[key] = {
                "position": str(state.position),
                "avg_cost": str(state.avg_cost),
                "realized_pnl": str(state.realized_pnl),
            }

        with open(path, "w") as f:
            json.dump(data, f, indent=2)