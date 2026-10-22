"""
Tensorix Network (TNX) - Block Structure & Merkle Tree
"""

import json
import struct
from typing import List
from .transaction import Transaction
from ..consensus.crypto import hash256, hash256_hex, double_hash256
from ..consensus.tensor_pow import (
    tensor_pow_hash_cpu,
    difficulty_to_target,
    verify_pow
)


def calculate_merkle_root(tx_hashes: List[str]) -> str:
    """Calculate double-hash Merkle tree root of transaction hashes."""
    if not tx_hashes:
        return hash256_hex(b"EMPTY_BLOCK")
    
    current_level = [bytes.fromhex(txid) for txid in tx_hashes]
    while len(current_level) > 1:
        if len(current_level) % 2 != 0:
            current_level.append(current_level[-1])  # Duplicate last element if odd
            
        next_level = []
        for i in range(0, len(current_level), 2):
            combined = current_level[i] + current_level[i + 1]
            next_level.append(double_hash256(combined))
        current_level = next_level
        
    return current_level[0].hex()


class Block:
    def __init__(
        self,
        index: int,
        prev_hash: str,
        timestamp: int,
        difficulty: float,
        nonce: int = 0,
        transactions: List[Transaction] = None,
        merkle_root: str = "",
        block_hash: str = ""
    ):
        self.index = int(index)
        self.prev_hash = prev_hash
        self.timestamp = int(timestamp)
        self.difficulty = float(difficulty)
        self.nonce = int(nonce)
        if not 0 <= self.index < 2**32:
            raise ValueError("Block index outside uint32")
        if not 0 <= self.timestamp < 2**64 or not 0 <= self.nonce < 2**64:
            raise ValueError("Block timestamp or nonce outside uint64")
        self.transactions = transactions or []
        self.merkle_root = merkle_root or self.compute_merkle_root()
        self.hash = block_hash or self.compute_hash()

    def compute_merkle_root(self) -> str:
        """Calculate Merkle root of all transactions in this block."""
        txids = [tx.txid for tx in self.transactions]
        return calculate_merkle_root(txids)

    def header_bytes(self) -> bytes:
        """
        Deterministic binary serialization of block header excluding nonce.
        This forms the cryptographic seed fed into Tensor-PoW.
        """
        payload = (
            struct.pack("<I", self.index) +
            bytes.fromhex(self.prev_hash) +
            bytes.fromhex(self.merkle_root) +
            struct.pack("<Q", self.timestamp) +
            struct.pack("<d", self.difficulty)
        )
        return hash256(payload)

    def compute_hash(self) -> str:
        """Compute the final Tensor-PoW hash for this block using the current nonce."""
        h_bytes = self.header_bytes()
        pow_bytes = tensor_pow_hash_cpu(h_bytes, self.nonce)
        return pow_bytes.hex()

    def verify_pow(self) -> bool:
        """Verify both the claimed block identity and its proof of work."""
        try:
            target = difficulty_to_target(self.difficulty)
            actual_hash = self.compute_hash()
            return self.hash == actual_hash and int(actual_hash, 16) <= target
        except (ValueError, TypeError, OverflowError, struct.error):
            return False

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "hash": self.hash,
            "prev_hash": self.prev_hash,
            "merkle_root": self.merkle_root,
            "timestamp": self.timestamp,
            "difficulty": self.difficulty,
            "nonce": self.nonce,
            "tx_count": len(self.transactions),
            "transactions": [tx.to_dict() for tx in self.transactions]
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Block":
        txs = [Transaction.from_dict(tx_data) for tx_data in data.get("transactions", [])]
        return cls(
            index=data["index"],
            prev_hash=data["prev_hash"],
            timestamp=data["timestamp"],
            difficulty=data["difficulty"],
            nonce=data["nonce"],
            transactions=txs,
            merkle_root=data.get("merkle_root", ""),
            block_hash=data.get("hash", "")
        )

