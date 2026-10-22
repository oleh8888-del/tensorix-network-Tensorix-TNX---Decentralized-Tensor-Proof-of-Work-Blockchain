"""
Tensorix Network (TNX) - Transaction Model
Secure Ed25519-signed transactions with replay-protection nonces and Coinbase generation.
"""

import json
import re
from ..consensus.crypto import (
    hash256_hex,
    pub_to_address,
    sign_message,
    verify_signature
)

# 1 TNX = 100,000,000 atomic units (Tensors)
COIN = 100_000_000

# Minimum & Default transaction fee: 10 TNX (100% routed directly to Founder Wallet)
MIN_TX_FEE = 10 * COIN
DEFAULT_TX_FEE = 10 * COIN


def valid_address(address: str) -> bool:
    return isinstance(address, str) and re.fullmatch(r"tnx1[0-9a-f]{40}", address) is not None


class Transaction:
    def __init__(
        self,
        sender: str,
        recipient: str,
        amount: int,          # in atomic units
        fee: int = DEFAULT_TX_FEE,  # default 10 TNX
        nonce: int = 0,
        public_key: str = "",
        signature: str = "",
        txid: str = ""
    ):
        self.sender = sender
        self.recipient = recipient
        self.amount = int(amount)
        self.fee = int(fee)
        self.nonce = int(nonce)
        self.public_key = public_key
        self.signature = signature
        self.txid = txid or self.calculate_txid()

    def payload_bytes(self) -> bytes:
        """Deterministic binary payload for signature generation and verification."""
        data = {
            "sender": self.sender,
            "recipient": self.recipient,
            "amount": self.amount,
            "fee": self.fee,
            "nonce": self.nonce
        }
        return json.dumps(data, sort_keys=True).encode("utf-8")

    def calculate_txid(self) -> str:
        """Calculate unique transaction ID (hash of payload + signature)."""
        data = {
            "payload": self.payload_bytes().decode("utf-8"),
            "signature": self.signature,
            "public_key": self.public_key
        }
        return hash256_hex(json.dumps(data, sort_keys=True).encode("utf-8"))

    def sign(self, private_key_hex: str):
        """Sign transaction payload with Ed25519 private key."""
        self.signature = sign_message(private_key_hex, self.payload_bytes())
        self.txid = self.calculate_txid()

    def is_coinbase(self) -> bool:
        """Check if this is a mining reward transaction."""
        return self.sender == "COINBASE"

    def is_valid(self, *, minimum_fee: int = MIN_TX_FEE) -> bool:
        """Verify signatures; only block validation may select historical fee rules."""
        if not valid_address(self.recipient) or self.nonce < 0 or self.fee < 0:
            return False
        if self.txid != self.calculate_txid():
            return False
        if self.is_coinbase():
            return self.amount >= 0 and self.fee == 0 and not self.public_key and not self.signature
        if self.amount <= 0 or self.fee < minimum_fee or not valid_address(self.sender):
            return False
        if not self.signature or not self.public_key:
            return False
        try:
            pub = bytes.fromhex(self.public_key)
            return len(pub) == 32 and self.sender == pub_to_address(pub) and verify_signature(self.public_key, self.payload_bytes(), self.signature)
        except (ValueError, TypeError):
            return False

    def to_dict(self) -> dict:
        return {
            "txid": self.txid,
            "sender": self.sender,
            "recipient": self.recipient,
            "amount": self.amount,
            "fee": self.fee,
            "nonce": self.nonce,
            "public_key": self.public_key,
            "signature": self.signature
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Transaction":
        return cls(
            sender=data["sender"],
            recipient=data["recipient"],
            amount=data["amount"],
            fee=data.get("fee", 0),
            nonce=data.get("nonce", 0),
            public_key=data.get("public_key", ""),
            signature=data.get("signature", ""),
            txid=data.get("txid", "")
        )

    @staticmethod
    def create_coinbase(recipient: str, reward_amount: int, block_index: int) -> "Transaction":
        """Generate special Coinbase transaction with miner reward."""
        tx = Transaction(
            sender="COINBASE",
            recipient=recipient,
            amount=reward_amount,
            fee=0,
            nonce=block_index,
            public_key="",
            signature=""
        )
        tx.txid = tx.calculate_txid()
        return tx

