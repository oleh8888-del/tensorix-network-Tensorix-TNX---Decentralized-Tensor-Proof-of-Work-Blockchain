"""Offline regressions. Accounting tests stub PoW; golden-genesis tests do not."""
import contextlib
import io
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tensorix.blockchain.block import Block
from tensorix.blockchain.chain import Blockchain, COIN, FOUNDER_ADDRESS
from tensorix.blockchain.transaction import Transaction
from tensorix.consensus.crypto import generate_keypair, hash256_hex
from tensorix.consensus.tensor_pow import difficulty_to_target
from tensorix.genesis import get_genesis_block, GENESIS_HASH

MINER = "tnx1" + "a" * 40


class GoldenConsensus(unittest.TestCase):
    def test_blake3_known_vector(self):
        self.assertEqual(hash256_hex(b""), "af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262")

    def test_public_genesis_matches_real_pow(self):
        genesis = get_genesis_block()
        self.assertEqual(genesis.compute_hash(), GENESIS_HASH)
        self.assertTrue(genesis.verify_pow())
        genesis.hash = "f" * 64
        self.assertFalse(genesis.verify_pow())

    def test_invalid_difficulty_fails_closed(self):
        for value in (0, -1, .5, math.nan, math.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                difficulty_to_target(value)

    def test_genesis_survives_validated_disk_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            chain = Blockchain(directory)
            self.assertTrue(chain.submit_block(get_genesis_block())[0])
            reloaded = Blockchain(directory)
            self.assertEqual(reloaded.get_latest_block().hash, GENESIS_HASH)
            self.assertEqual(reloaded.get_balance(FOUNDER_ADDRESS), 10 * COIN)

    def test_corrupt_chain_file_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blockchain.json"
            raw = b'{"not": "a chain"}'
            path.write_bytes(raw)
            with self.assertRaises(ValueError):
                Blockchain(directory)
            self.assertEqual(path.read_bytes(), raw)

    def test_forged_genesis_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            chain = Blockchain(directory)
            block = get_genesis_block()
            block.hash = "0" * 64
            with patch.object(Block, "verify_pow", return_value=True):
                self.assertFalse(chain.submit_block(block)[0])


class AccountValidation(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.chain = Blockchain(self.directory.name)
        genesis = get_genesis_block()
        self.chain.chain = [genesis]
        self.chain.apply_block_to_state(genesis)
        self.secret, self.public, self.sender = generate_keypair()
        self.chain.balances[self.sender] = 100 * COIN

    def tx(self, nonce=0, amount=COIN, **kwargs):
        tx = Transaction(self.sender, MINER, amount, fee=10 * COIN,
                         nonce=nonce, public_key=self.public, **kwargs)
        tx.sign(self.secret)
        return tx

    def block(self, transactions=None):
        template = self.chain.get_block_template(MINER)
        if transactions is not None:
            template["transactions"] = [t for t in template["transactions"] if t["sender"] == "COINBASE"] + [t.to_dict() for t in transactions]
            template.pop("merkle_root")
        return Block.from_dict(template | {"nonce": 0})

    def submit_accounting(self, block):
        with patch.object(Block, "verify_pow", return_value=True), contextlib.redirect_stdout(io.StringIO()):
            return self.chain.submit_block(block, persist=False)

    def test_exact_two_percent_coinbase_split(self):
        block = self.block()
        self.assertEqual([(t.recipient, t.amount) for t in block.transactions],
                         [(MINER, 980_000_000), (FOUNDER_ADDRESS, 20_000_000)])
        self.assertTrue(self.submit_accounting(block)[0])
        self.assertEqual(self.chain.get_balance(MINER), 980_000_000)

    def test_missing_founder_fee_rejected(self):
        block = self.block()
        block.transactions = [Transaction.create_coinbase(MINER, 10 * COIN, block.index)]
        block.merkle_root = block.compute_merkle_root()
        self.assertFalse(self.submit_accounting(block)[0])

    def test_difficulty_cannot_be_selected_by_miner(self):
        block = self.block()
        block.difficulty = 1.01
        self.assertFalse(self.submit_accounting(block)[0])

    def test_overspend_rejected_without_state_change(self):
        self.chain.balances[self.sender] = 5 * COIN
        block = self.block([self.tx()])
        before = self.chain.balances.copy()
        self.assertFalse(self.submit_accounting(block)[0])
        self.assertEqual(self.chain.balances, before)
        self.assertEqual(len(self.chain.chain), 1)

    def test_repeated_nonce_in_same_block_rejected(self):
        block = self.block([self.tx(amount=COIN), self.tx(amount=2 * COIN)])
        self.assertFalse(self.submit_accounting(block)[0])

    def test_signed_sequence_and_transaction_fee_routing(self):
        block = self.block([self.tx(0), self.tx(1)])
        self.assertTrue(self.submit_accounting(block)[0])
        self.assertEqual(self.chain.get_account_nonce(self.sender), 2)
        self.assertEqual(self.chain.get_balance(self.sender), 78 * COIN)
        self.assertEqual(self.chain.get_balance(FOUNDER_ADDRESS), 30 * COIN + 20_000_000)

    def test_forged_transaction_id_rejected(self):
        tx = self.tx()
        tx.txid = "1" * 64
        self.assertFalse(tx.is_valid())
        self.assertFalse(self.submit_accounting(self.block([tx]))[0])

    def test_negative_coinbase_rejected(self):
        block = self.block()
        block.transactions[0].amount = -COIN
        block.transactions[0].txid = block.transactions[0].calculate_txid()
        block.merkle_root = block.compute_merkle_root()
        self.assertFalse(self.submit_accounting(block)[0])

    def test_malformed_public_key_rejected_without_exception(self):
        tx = self.tx()
        tx.public_key = "not hex"
        tx.txid = tx.calculate_txid()
        self.assertFalse(tx.is_valid())

    def test_mempool_duplicate_and_nonce_gap_rejected(self):
        tx = self.tx()
        self.assertTrue(self.chain.add_transaction(tx)[0])
        self.assertFalse(self.chain.add_transaction(tx)[0])
        self.assertFalse(self.chain.add_transaction(self.tx(2))[0])
        self.assertTrue(self.chain.add_transaction(self.tx(1))[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
