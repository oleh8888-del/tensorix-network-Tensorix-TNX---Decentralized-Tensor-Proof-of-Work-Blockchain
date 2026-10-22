"""
Tensorix Network (TNX) - Blockchain Engine & State Machine
Handles ledger state, mempool, validation, block persistence, and block templates.
"""

import os
import json
import time
import math
import tempfile
import threading
from functools import wraps
from typing import List, Dict, Optional
from .block import Block
from .transaction import Transaction, COIN, valid_address
from ..consensus.difficulty import calculate_next_difficulty, MIN_DIFFICULTY
from ..consensus.crypto import hash256_hex

# Emission and Fee parameters
INITIAL_REWARD = 10 * COIN       # 10 TNX
HALVING_INTERVAL = 1_051_200     # Halving every ~2 years (at 60s per block)
MAX_SUPPLY = 21_000_000 * COIN   # 21M TNX

# Founder Wallet & Network Fee configuration
FOUNDER_ADDRESS = "tnx1b050bd6e525ac254ab212efce117cc636eb1166e"
POOL_FEE_PCT = 0.02              # 2% Mining Pool fee -> Founder Wallet
MIN_TX_FEE = 10 * COIN           # 10 TNX Transaction fee -> Founder Wallet
GENESIS_HASH = "0003692a2068dc16ed9092c63a22d35f74e8b0e213918a88d10f3e37bdba315b"

# This exact pre-upgrade block used the original fee-to-coinbase accounting.
# The real PoW/hash binding is still verified before its transactions are accepted.
# No other block, mempool admission or wallet transfer receives this exception.
LEGACY_FEE_BLOCK_HEIGHT = 2
LEGACY_FEE_BLOCK_HASH = "000d11c2869efd16eff2d04e79f75bd6b807c4935b21e7b11c91baa9f7749de5"


def uses_legacy_fee_rules(block: Block) -> bool:
    return block.index == LEGACY_FEE_BLOCK_HEIGHT and block.hash == LEGACY_FEE_BLOCK_HASH


def locked(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._state_lock:
            return method(self, *args, **kwargs)
    return call


def atomic_block_update(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._state_lock:
            previous = (self.chain.copy(), self.balances.copy(),
                        self.account_nonces.copy(), self.mempool.copy())
            try:
                return method(self, *args, **kwargs)
            except Exception:
                # A failed durable commit must not leave an accepted in-memory block.
                self.chain, self.balances, self.account_nonces, self.mempool = previous
                raise
    return call


class Blockchain:
    def __init__(self, data_dir: str = "tensorix_data"):
        self._state_lock = threading.RLock()
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.chain_file = os.path.join(self.data_dir, "blockchain.json")
        
        self.chain: List[Block] = []
        self.balances: Dict[str, int] = {}
        self.account_nonces: Dict[str, int] = {}
        self.mempool: Dict[str, Transaction] = {}
        
        self.load_or_initialize()

    def get_block_reward(self, height: int) -> int:
        """Calculate block subsidy with halving."""
        halvings = height // HALVING_INTERVAL
        if halvings >= 64:
            return 0
        reward = INITIAL_REWARD >> halvings
        return reward

    @locked
    def get_latest_block(self) -> Block:
        return self.chain[-1]

    @locked
    def get_balance(self, address: str) -> int:
        return self.balances.get(address, 0)

    @locked
    def get_account_nonce(self, address: str) -> int:
        return self.account_nonces.get(address, 0)

    @locked
    def load_or_initialize(self):
        """Validate persisted history; never replace a corrupt chain with an empty one."""
        if os.path.exists(self.chain_file):
            try:
                with open(self.chain_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, list) or not data:
                    raise ValueError("Persisted chain must be a nonempty list")
                for raw in data:
                    ok, reason = self.submit_block(Block.from_dict(raw), persist=False)
                    if not ok:
                        raise ValueError(f"Persisted block rejected: {reason}")
                print(f"[Tensorix Node] Validated {len(self.chain)} blocks from disk.")
                return
            except Exception as e:
                raise ValueError(f"Cannot load chain; original file retained: {e}") from e
        self.chain = []
        self.balances = {}
        self.account_nonces = {}

    @locked
    def rebuild_state(self):
        """Recompute balances and nonces from genesis to top block."""
        self.balances.clear()
        self.account_nonces.clear()
        for block in self.chain:
            self.apply_block_to_state(block)

    def apply_block_to_state(self, block: Block):
        """Update account balances and transaction nonces."""
        legacy_fees = uses_legacy_fee_rules(block)
        for tx in block.transactions:
            if tx.is_coinbase():
                self.balances[tx.recipient] = self.balances.get(tx.recipient, 0) + tx.amount
            else:
                total_deduction = tx.amount + tx.fee
                self.balances[tx.sender] = self.balances.get(tx.sender, 0) - total_deduction
                self.balances[tx.recipient] = self.balances.get(tx.recipient, 0) + tx.amount
                # Legacy block 2 already includes its fee in its coinbase reward.
                if not legacy_fees:
                    self.balances[FOUNDER_ADDRESS] = self.balances.get(FOUNDER_ADDRESS, 0) + tx.fee
                self.account_nonces[tx.sender] = tx.nonce + 1

    @locked
    def save_chain(self):
        """Persist blockchain to disk."""
        path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.data_dir, delete=False) as f:
                path = f.name
                json.dump([b.to_dict() for b in self.chain], f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(path, self.chain_file)
        finally:
            if path and os.path.exists(path):
                os.unlink(path)

    @locked
    def add_transaction(self, tx: Transaction) -> tuple[bool, str]:
        """Validate and insert transaction into the local mempool."""
        if tx.is_coinbase() or not tx.is_valid():
            return False, "Invalid signature or transaction format."
        if tx.txid in self.mempool:
            return False, "Transaction already in mempool."

        if tx.fee < MIN_TX_FEE:
            return False, f"Fee {tx.fee / COIN:.2f} TNX is below minimum required {MIN_TX_FEE / COIN:.2f} TNX."

        # Balance check (including pending transactions in mempool)
        current_balance = self.get_balance(tx.sender)
        required = tx.amount + tx.fee
        
        # Deduct any pending mempool transactions from this sender
        for mem_tx in self.mempool.values():
            if mem_tx.sender == tx.sender:
                required += mem_tx.amount + mem_tx.fee

        if current_balance < required:
            return False, f"Insufficient balance: have {current_balance / COIN:.4f} TNX, need {required / COIN:.4f} TNX."

        expected_nonce = self.get_account_nonce(tx.sender) + sum(1 for t in self.mempool.values() if t.sender == tx.sender)
        if tx.nonce != expected_nonce:
            return False, f"Invalid nonce: expected {expected_nonce}, got {tx.nonce}."

        self.mempool[tx.txid] = tx
        return True, "Transaction accepted into mempool."

    @locked
    def get_next_difficulty(self) -> float:
        """Calculate next difficulty based on chain history."""
        if len(self.chain) < 2:
            return MIN_DIFFICULTY
        history = [{"timestamp": b.timestamp, "difficulty": b.difficulty} for b in self.chain]
        return calculate_next_difficulty(history)

    @locked
    def get_block_template(self, miner_address: str) -> dict:
        """Create a candidate block template for miners."""
        if not valid_address(miner_address):
            raise ValueError("A complete TNX payout address is required")
        latest = self.get_latest_block()
        next_index = latest.index + 1
        next_diff = self.get_next_difficulty()
        
        # Collect candidate transactions from mempool
        candidate_txs: List[Transaction] = []
        for tx in list(self.mempool.values())[:500]:  # up to 500 txs per block
            candidate_txs.append(tx)

        # Block subsidy
        reward = self.get_block_reward(next_index)

        # 2% Pool Fee: if miner is not Founder Wallet, split reward 98% miner / 2% founder
        if miner_address != FOUNDER_ADDRESS and POOL_FEE_PCT > 0:
            pool_fee = int(reward * POOL_FEE_PCT)
            miner_reward = reward - pool_fee
            coinbase_txs = [
                Transaction.create_coinbase(miner_address, miner_reward, next_index),
                Transaction.create_coinbase(FOUNDER_ADDRESS, pool_fee, next_index)
            ]
        else:
            coinbase_txs = [
                Transaction.create_coinbase(miner_address, reward, next_index)
            ]
        
        all_txs = coinbase_txs + candidate_txs
        tx_hashes = [tx.txid for tx in all_txs]
        
        from .block import calculate_merkle_root
        merkle_root = calculate_merkle_root(tx_hashes)
        now_ts = max(int(time.time()), latest.timestamp + 1)

        # Construct template block
        template_block = Block(
            index=next_index,
            prev_hash=latest.hash,
            timestamp=now_ts,
            difficulty=next_diff,
            nonce=0,
            transactions=all_txs,
            merkle_root=merkle_root
        )

        header_bytes = template_block.header_bytes()
        from ..consensus.tensor_pow import difficulty_to_target

        pool_fee_val = (int(reward * POOL_FEE_PCT) / COIN) if miner_address != FOUNDER_ADDRESS else 0.0
        miner_reward_val = ((reward - int(reward * POOL_FEE_PCT)) / COIN) if miner_address != FOUNDER_ADDRESS else (reward / COIN)

        return {
            "index": next_index,
            "prev_hash": latest.hash,
            "header_hash": header_bytes.hex(),
            "merkle_root": merkle_root,
            "timestamp": now_ts,
            "difficulty": next_diff,
            "target": hex(difficulty_to_target(next_diff)),
            "reward_tnx": reward / COIN,
            "miner_reward_tnx": miner_reward_val,
            "pool_fee_tnx": pool_fee_val,
            "pool_fee_pct": 2.0 if miner_address != FOUNDER_ADDRESS else 0.0,
            "pool_fee_recipient": FOUNDER_ADDRESS,
            "tx_count": len(all_txs),
            "transactions": [tx.to_dict() for tx in all_txs]
        }

    @atomic_block_update
    def submit_block(self, block: Block, *, persist: bool = True) -> tuple[bool, str]:
        """Validate and append new mined block to the blockchain."""
        if not math.isfinite(block.difficulty) or block.difficulty < MIN_DIFFICULTY:
            return False, "Invalid block difficulty."
        if not 0 <= block.index < 2**32 or not 0 <= block.nonce < 2**64:
            return False, "Block index or nonce outside wire format bounds."
        if not block.transactions or block.merkle_root != block.compute_merkle_root():
            return False, "Missing transactions or invalid Merkle root."
        ids = [tx.txid for tx in block.transactions]
        if len(set(ids)) != len(ids) or any(tx.txid != tx.calculate_txid() for tx in block.transactions):
            return False, "Duplicate or incorrect transaction ID."
        if not self.chain:
            # First block must be genesis
            if block.index != 0 or block.prev_hash != "0" * 64 or block.hash != GENESIS_HASH:
                return False, "First block must match the pinned Tensorix genesis."
            if not block.verify_pow():
                return False, "Genesis block PoW verification failed."
            self.chain.append(block)
            self.apply_block_to_state(block)
            if persist:
                self.save_chain()
            return True, "Genesis block accepted."

        latest = self.get_latest_block()
        if block.index != latest.index + 1:
            return False, f"Invalid block index: expected {latest.index + 1}, got {block.index}."

        if block.prev_hash != latest.hash:
            return False, f"Invalid prev_hash: expected {latest.hash}, got {block.prev_hash}."
        if block.difficulty != self.get_next_difficulty():
            return False, "Block difficulty does not match the chain retarget."

        if block.timestamp <= latest.timestamp:
            return False, "Block timestamp must be greater than previous block."

        if block.timestamp > time.time() + 7200:
            return False, "Block timestamp is too far in the future."

        # Verify Proof of Work
        if not block.verify_pow():
            return False, "Tensor-PoW verification failed: hash does not satisfy target difficulty."

        # Verify Merkle root
        expected_merkle = block.compute_merkle_root()
        if block.merkle_root != expected_merkle:
            return False, f"Merkle root mismatch: expected {expected_merkle}, got {block.merkle_root}."

        # Verify transactions
        if not block.transactions:
            return False, "Block has no transactions."

        coinbase_txs: List[Transaction] = []
        regular_txs: List[Transaction] = []
        seen_regular = False
        legacy_fees = uses_legacy_fee_rules(block)
        minimum_fee = 0 if legacy_fees else MIN_TX_FEE

        for tx in block.transactions:
            if tx.is_coinbase():
                if seen_regular:
                    return False, "Coinbase transactions must appear at the beginning of the block."
                if not tx.is_valid() or tx.nonce != block.index:
                    return False, "Invalid coinbase amount, format or height."
                coinbase_txs.append(tx)
            else:
                seen_regular = True
                if tx.fee < minimum_fee:
                    return False, f"Tx {tx.txid} fee too low: min fee is {minimum_fee / COIN} TNX."
                if not tx.is_valid(minimum_fee=minimum_fee):
                    return False, f"Invalid transaction signature or format for tx {tx.txid}."
                regular_txs.append(tx)

        if not coinbase_txs:
            return False, "Block must contain at least one Coinbase transaction."

        max_allowed_reward = self.get_block_reward(block.index)
        if legacy_fees:
            max_allowed_reward += sum(tx.fee for tx in regular_txs)
        total_coinbase = sum(tx.amount for tx in coinbase_txs)

        if total_coinbase > max_allowed_reward:
            return False, f"Coinbase reward too high: claimed {total_coinbase}, max {max_allowed_reward}."

        # If miner is not founder, verify pool fee split (at least 2% to FOUNDER_ADDRESS)
        if any(tx.recipient != FOUNDER_ADDRESS for tx in coinbase_txs):
            founder_coinbase_sum = sum(tx.amount for tx in coinbase_txs if tx.recipient == FOUNDER_ADDRESS)
            expected_pool_fee = int(max_allowed_reward * POOL_FEE_PCT)
            if founder_coinbase_sum < expected_pool_fee:
                return False, f"Block missing required 2% pool fee ({expected_pool_fee / COIN} TNX) to founder {FOUNDER_ADDRESS}."

        # Validate sequential account transitions before touching live balances.
        balances = self.balances.copy()
        nonces = self.account_nonces.copy()
        for tx in coinbase_txs:
            balances[tx.recipient] = balances.get(tx.recipient, 0) + tx.amount
        for tx in regular_txs:
            if tx.nonce != nonces.get(tx.sender, 0):
                return False, "Transaction nonce is not the next account nonce."
            debit = tx.amount + tx.fee
            if balances.get(tx.sender, 0) < debit:
                return False, "Transaction overspends its account balance."
            balances[tx.sender] -= debit
            balances[tx.recipient] = balances.get(tx.recipient, 0) + tx.amount
            if not legacy_fees:
                balances[FOUNDER_ADDRESS] = balances.get(FOUNDER_ADDRESS, 0) + tx.fee
            nonces[tx.sender] = tx.nonce + 1

        # Apply block to state and remove confirmed transactions from mempool
        self.apply_block_to_state(block)
        for tx in regular_txs:
            self.mempool.pop(tx.txid, None)

        self.chain.append(block)
        # Recheck pending transactions against the newly committed state.
        pending = sorted(self.mempool.values(), key=lambda tx: (tx.sender, tx.nonce))
        self.mempool.clear()
        for tx in pending:
            self.add_transaction(tx)
        if persist:
            self.save_chain()
            print(f"[Tensorix Node] Accepted block #{block.index} [Diff: {block.difficulty:.2f}] Hash: {block.hash[:16]}...")
        return True, f"Block #{block.index} accepted successfully."

