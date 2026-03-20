#src/reconciliation/fee_normalizer.py
class FeeNormalizer:
    def __init__(self, price_provider):
        self.price_provider = price_provider

    def normalize(self, execution: Execution) -> Decimal:
        if execution.commission_asset == execution.symbol[-4:]:  # naive quote detection
            return execution.commission

        price = self.price_provider.get_price(execution.commission_asset, execution.timestamp)
        if price is None:
            raise Exception(f"Cannot resolve fee price for {execution.commission_asset}")

        return execution.commission * price