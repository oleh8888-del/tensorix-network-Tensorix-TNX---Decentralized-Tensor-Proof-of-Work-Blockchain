"""Wallet transfer accounting; no network transfers or operator keys are used."""
import contextlib
import io
import tempfile
import unittest
from unittest.mock import patch

import httpx

from tensorix.blockchain.block import Block
from tensorix.blockchain.chain import Blockchain, COIN, FOUNDER_ADDRESS
from tensorix.blockchain.transaction import Transaction
from tensorix.consensus.crypto import generate_keypair
from tensorix.genesis import get_genesis_block
from tensorix.wallet.wallet_cli import send_tnx, tnx_to_units

MINER = "tnx1" + "a" * 40
RECIPIENT = "tnx1" + "b" * 40


class TransferFeeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.chain = Blockchain(self.directory.name)
        self.chain.submit_block(get_genesis_block())
        self.secret, self.public, self.sender = generate_keypair()
        # Isolated account fixture; this does not mint or transfer real TNX.
        self.chain.balances[self.sender] = 50 * COIN

    def transaction(self, fee=10 * COIN):
        tx = Transaction(self.sender, RECIPIENT, 5 * COIN, fee=fee,
                         nonce=0, public_key=self.public)
        tx.sign(self.secret)
        return tx

    def test_five_tnx_transfer_debits_fifteen_and_credits_fee_once(self):
        tx = self.transaction()
        self.assertTrue(self.chain.add_transaction(tx)[0])
        block = Block.from_dict(self.chain.get_block_template(MINER) | {"nonce": 0})
        coinbases = [t for t in block.transactions if t.is_coinbase()]
        self.assertEqual(sum(t.amount for t in coinbases), 10 * COIN)
        self.assertTrue(all(t.fee == 0 for t in coinbases))
        with patch.object(Block, "verify_pow", return_value=True):
            self.assertTrue(self.chain.submit_block(block, persist=False)[0])
        self.assertEqual(self.chain.get_balance(self.sender), 35 * COIN)
        self.assertEqual(self.chain.get_balance(RECIPIENT), 5 * COIN)
        self.assertEqual(self.chain.get_balance(MINER), 980_000_000)
        self.assertEqual(self.chain.get_balance(FOUNDER_ADDRESS), 2_020_000_000)

    def test_new_low_fee_transfer_is_rejected_without_debit(self):
        before = self.chain.balances.copy()
        self.assertFalse(self.chain.add_transaction(self.transaction(fee=10000))[0])
        self.assertEqual(self.chain.balances, before)
        self.assertEqual(self.chain.mempool, {})

    def test_low_fee_in_a_new_mined_block_is_also_rejected(self):
        template = self.chain.get_block_template(MINER)
        template["transactions"].append(self.transaction(fee=10000).to_dict())
        template.pop("merkle_root")
        block = Block.from_dict(template | {"nonce": 0})
        with patch.object(Block, "verify_pow", return_value=True):
            ok, reason = self.chain.submit_block(block, persist=False)
        self.assertFalse(ok)
        self.assertIn("fee too low", reason)
        self.assertEqual(self.chain.get_balance(self.sender), 50 * COIN)

    def test_new_block_cannot_add_transfer_fee_to_its_mining_reward(self):
        self.assertTrue(self.chain.add_transaction(self.transaction())[0])
        block = Block.from_dict(self.chain.get_block_template(MINER) | {"nonce": 0})
        block.transactions[0].amount += 10 * COIN
        block.transactions[0].txid = block.transactions[0].calculate_txid()
        block.merkle_root = block.compute_merkle_root()
        with patch.object(Block, "verify_pow", return_value=True):
            ok, reason = self.chain.submit_block(block, persist=False)
        self.assertFalse(ok)
        self.assertIn("Coinbase reward too high", reason)
        self.assertEqual(self.chain.get_balance(self.sender), 50 * COIN)

    def test_coinbase_needs_no_ten_tnx_transaction_fee(self):
        block = Block.from_dict(self.chain.get_block_template(MINER) | {"nonce": 0})
        self.assertEqual([t.fee for t in block.transactions], [0, 0])
        with patch.object(Block, "verify_pow", return_value=True):
            self.assertTrue(self.chain.submit_block(block, persist=False)[0])
        self.assertEqual(self.chain.get_balance(MINER), 980_000_000)
        self.assertEqual(self.chain.get_balance(FOUNDER_ADDRESS), 1_020_000_000)


class WalletFeeTests(unittest.TestCase):
    def test_smallest_units_are_preserved_exactly(self):
        self.assertEqual(tnx_to_units("0.00000003", name="Amount"), 3)
        self.assertEqual(tnx_to_units("10", name="Fee"), 1_000_000_000)
        self.assertEqual(tnx_to_units("123456789012345678901.12345678", name="Amount"),
                         12345678901234567890112345678)
        for value in ("0", "-1", "NaN", "Infinity", "0.000000001"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                tnx_to_units(value, name="Amount")

    def test_default_wallet_fee_is_ten_and_signature_covers_it(self):
        private, public, address = generate_keypair()
        wallet = {"private_key": private, "public_key": public, "address": address}
        sent = []

        def transport(request):
            if request.method == "GET":
                return httpx.Response(200, json={"nonce": 0, "balance_atomic": 50 * COIN})
            import json
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"success": True})

        real_client = httpx.Client

        def client(**kwargs):
            return real_client(transport=httpx.MockTransport(transport), **kwargs)

        with patch("tensorix.wallet.wallet_cli.load_wallet", return_value=wallet), \
             patch("tensorix.wallet.wallet_cli.httpx.Client", side_effect=client), \
             contextlib.redirect_stdout(io.StringIO()):
            send_tnx(RECIPIENT, "0.00000003")
        self.assertEqual(len(sent), 1)
        tx = Transaction.from_dict(sent[0])
        self.assertEqual(tx.amount, 3)
        self.assertEqual(tx.fee, 10 * COIN)
        self.assertTrue(tx.is_valid())

    def test_invalid_amount_or_fee_does_not_read_keys_or_contact_node(self):
        for amount, fee in (("5", "0.0001"), ("NaN", "10"), ("0.000000001", "10")):
            with self.subTest(amount=amount, fee=fee), \
                 patch("tensorix.wallet.wallet_cli.load_wallet") as wallet, \
                 patch("tensorix.wallet.wallet_cli.httpx.Client") as client, \
                 contextlib.redirect_stdout(io.StringIO()):
                send_tnx(RECIPIENT, amount, fee)
                wallet.assert_not_called()
                client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
