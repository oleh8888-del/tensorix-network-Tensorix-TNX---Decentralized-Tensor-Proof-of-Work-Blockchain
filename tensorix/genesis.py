"""Pinned public Tensorix genesis. This module never creates wallet keys."""
from .blockchain.block import Block
from .blockchain.transaction import Transaction

FOUNDER_ADDRESS = "tnx1b050bd6e525ac254ab212efce117cc636eb1166e"
FOUNDER_MESSAGE = "Tensorix 2026: Autonomous Tensor-PoW Powered by NVIDIA Tensor Cores"
GENESIS_HASH = "0003692a2068dc16ed9092c63a22d35f74e8b0e213918a88d10f3e37bdba315b"


def get_genesis_block() -> Block:
    tx = Transaction(
        sender="COINBASE", recipient=FOUNDER_ADDRESS, amount=1_000_000_000,
        fee=0, nonce=0, public_key="", signature=FOUNDER_MESSAGE.encode().hex(),
        txid="b516b0a1d1137b6d312c3a7c0d083f0e60e88c834da4a6a9a940002efc7b0206",
    )
    return Block(index=0, prev_hash="0" * 64, timestamp=1792456684,
                 difficulty=1.0, nonce=7092, transactions=[tx], block_hash=GENESIS_HASH)


def mine_genesis_block(founder_address: str, difficulty: float = 1.0) -> Block:
    """Compatibility entry point: return and verify the existing network genesis."""
    if founder_address != FOUNDER_ADDRESS or difficulty != 1.0:
        raise ValueError("A different founder or difficulty creates a different network")
    block = get_genesis_block()
    if not block.verify_pow():
        raise ValueError("Pinned genesis failed deterministic proof verification")
    return block
