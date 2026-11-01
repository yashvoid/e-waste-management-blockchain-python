from collections.abc import Iterable

from app.blockchain.business import BUSINESS_TYPES, BusinessLedger
from app.blockchain.participants import ParticipantLedger
from app.blockchain.processing import PROCESSING_TYPES, ProcessingLedger
from app.blockchain.structures import Block, Transaction, parse_utc_timestamp
from app.config.shared_network import SharedNetworkConfig


class ChainLedger:
    def __init__(self) -> None:
        self.participants = ParticipantLedger()
        self.business = BusinessLedger(self.participants)
        self.processing = ProcessingLedger(self.business, self.participants)

    @classmethod
    def from_blocks(cls, blocks: Iterable[Block], config: SharedNetworkConfig) -> "ChainLedger":
        ledger = cls()
        for block in blocks:
            ledger.begin_block(block.timestamp)
            for transaction in block.transactions:
                ledger.apply(transaction, block_timestamp=block.timestamp, height=block.height, config=config)
        return ledger

    def begin_block(self, block_timestamp: str) -> None:
        self.business.expire_due(parse_utc_timestamp(block_timestamp))

    def check(
        self,
        transaction: Transaction,
        *,
        block_timestamp: str,
        height: int,
        config: SharedNetworkConfig,
    ) -> None:
        self.participants.check(transaction, block_timestamp=block_timestamp, height=height, config=config)
        if transaction.tx_type in BUSINESS_TYPES:
            self.business.check(transaction, parse_utc_timestamp(block_timestamp))
        elif transaction.tx_type in PROCESSING_TYPES:
            self.processing.check(transaction)

    def apply(
        self,
        transaction: Transaction,
        *,
        block_timestamp: str,
        height: int,
        config: SharedNetworkConfig,
    ) -> None:
        self.check(transaction, block_timestamp=block_timestamp, height=height, config=config)
        self.participants.apply(transaction, block_timestamp=block_timestamp, height=height, config=config)
        if transaction.tx_type in BUSINESS_TYPES:
            self.business.apply(transaction, parse_utc_timestamp(block_timestamp))
        elif transaction.tx_type in PROCESSING_TYPES:
            self.processing.apply(transaction, parse_utc_timestamp(block_timestamp))
