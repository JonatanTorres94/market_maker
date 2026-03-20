class ExecutionPipeline:

    def __init__(
        self,
        reconciler,
        fee_normalizer,
        sequencer,
        ledger,
        buffer,
        snapshotter=None

    ):
        self.reconciler = reconciler
        self.fee_normalizer = fee_normalizer
        self.sequencer = sequencer
        self.ledger = ledger
        self.buffer = buffer
        self.snapshotter = snapshotter
        self._processed_count = 0

    def on_execution(self, execution):
        self.buffer.add(execution)

    def process(self):

        # 1. RECONCILIATION
        for state in self.buffer.get_all():
            if not state.is_reconciled:
                if self.reconciler.validate(state.execution):
                    state.is_reconciled = True

        # 2. FEE NORMALIZATION
        for state in self.buffer.get_all():
            if state.is_reconciled and not state.is_fee_resolved:
                fee = self.fee_normalizer.normalize(state.execution)
                state.commission_in_quote = fee
                state.is_fee_resolved = True

        # 3. SEQUENCING
        ready_states = self.buffer.get_ready()

        for state in ready_states:
            self.sequencer.add(state)

        ordered_states = self.sequencer.get_next_batch()

        # 4. LEDGER APPLY
        for state in ordered_states:
            self.ledger.apply(
                execution=state.execution,
                fee_in_quote=state.commission_in_quote
            )
            self.buffer.remove(state.key)
            self._processed_count += 1

            if self.snapshotter and self._processed_count % 100 == 0:
                self.snapshotter.dump("ledger_snapshot.json")