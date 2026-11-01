from chain_helpers import key_for_label, mine, sign_transaction
from app.blockchain.structures import Block, Transaction
from app.config.shared_network import SharedNetworkConfig
from app.storage.chain_storage import ChainStorage


def minute_timestamp(minute: int, second: int = 0) -> str:
    return f"2026-01-01T00:{minute:02d}:{second:02d}Z"


def extend_chain(chain: ChainStorage, config: SharedNetworkConfig, count: int, first_minute: int = 1) -> list[Block]:
    blocks: list[Block] = []
    parent = chain.store.tip
    for offset in range(count):
        block = _add_child(chain, config, parent, first_minute + offset, second=0, nonce=offset)
        blocks.append(block)
        parent = block
    return blocks


def add_sibling(chain: ChainStorage, config: SharedNetworkConfig, parent: Block, minute: int, second: int) -> Block:
    return _add_child(chain, config, parent, minute, second=second, nonce=100)


def _add_child(chain: ChainStorage, config: SharedNetworkConfig, parent: Block, minute: int, *, second: int, nonce: int) -> Block:
    transaction: Transaction = sign_transaction(
        config, key_for_label("storage-tester"), minute_timestamp(minute, second), nonce=nonce
    )
    block = mine(config, parent, [transaction], minute_timestamp(minute, 30))
    chain.add_block(block)
    return block
