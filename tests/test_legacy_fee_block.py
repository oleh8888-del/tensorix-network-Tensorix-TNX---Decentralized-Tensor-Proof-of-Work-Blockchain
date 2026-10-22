"""Real historical PoW and signatures; the fixture contains public ledger data only."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from tensorix.blockchain.block import Block
from tensorix.blockchain.chain import Blockchain, COIN, FOUNDER_ADDRESS, LEGACY_FEE_BLOCK_HASH


class LegacyFeeBlockTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.chain = Blockchain(self.directory.name)
        fixture = Path(__file__).parent / "fixtures" / "legacy-blocks-0-2.json"
        self.raw = json.loads(fixture.read_text(encoding="utf-8"))
        for raw in self.raw[:2]:
            self.assertTrue(self.chain.submit_block(Block.from_dict(raw), persist=False)[0])

    def test_existing_block_replays_real_proof_without_double_fee_credit(self):
        block = Block.from_dict(self.raw[2])
        self.assertEqual(block.hash, LEGACY_FEE_BLOCK_HASH)
        self.assertTrue(block.verify_pow())
        transfer = next(t for t in block.transactions if not t.is_coinbase())
        self.assertFalse(transfer.is_valid())  # New wallet/mempool policy remains 10 TNX.
        self.assertTrue(self.chain.submit_block(block)[0])
        self.assertEqual(self.chain.get_balance(transfer.recipient), 5 * COIN)
        self.assertEqual(self.chain.get_balance(FOUNDER_ADDRESS), 25 * COIN)
        self.assertEqual(sum(self.chain.balances.values()), 30 * COIN)
        reloaded = Blockchain(self.directory.name)
        self.assertEqual(reloaded.balances, self.chain.balances)
        self.assertEqual(reloaded.account_nonces, self.chain.account_nonces)

    def test_historical_transfer_is_not_exempt_in_mempool(self):
        block = Block.from_dict(self.raw[2])
        transfer = next(t for t in block.transactions if not t.is_coinbase())
        self.assertFalse(self.chain.add_transaction(transfer)[0])
        self.assertEqual(self.chain.get_balance(FOUNDER_ADDRESS), 20 * COIN)

    def test_changing_pinned_block_does_not_inherit_legacy_exemption(self):
        raw = copy.deepcopy(self.raw[2])
        raw["hash"] = "f" * 64
        self.assertFalse(self.chain.submit_block(Block.from_dict(raw), persist=False)[0])
        raw = copy.deepcopy(self.raw[2])
        raw["nonce"] += 1
        self.assertFalse(self.chain.submit_block(Block.from_dict(raw), persist=False)[0])
        self.assertEqual(len(self.chain.chain), 2)


if __name__ == "__main__":
    unittest.main()
