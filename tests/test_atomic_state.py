"""Real thread scheduling and failed persistence; PoW is deliberately stubbed."""
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from tensorix.blockchain.block import Block
from tensorix.blockchain.chain import Blockchain, FOUNDER_ADDRESS
from tensorix.genesis import get_genesis_block

MINER = "tnx1" + "a" * 40


class AtomicStateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.chain = Blockchain(self.directory.name)
        self.assertTrue(self.chain.submit_block(get_genesis_block())[0])

    def block(self):
        return Block.from_dict(self.chain.get_block_template(MINER) | {"nonce": 0})

    def test_concurrent_same_height_is_accepted_only_once(self):
        block = self.block()

        def delayed_proof(_block):
            time.sleep(.04)  # Release the GIL while the other caller tries to validate.
            return True

        with patch.object(Block, "verify_pow", delayed_proof), ThreadPoolExecutor(2) as executor:
            results = list(executor.map(lambda _: self.chain.submit_block(block), range(2)))
        self.assertEqual(sum(ok for ok, _ in results), 1)
        self.assertEqual([b.index for b in self.chain.chain], [0, 1])
        self.assertEqual(self.chain.get_balance(MINER), 980_000_000)
        self.assertEqual(self.chain.get_balance(FOUNDER_ADDRESS), 1_020_000_000)

    def test_failed_replace_retains_disk_and_restores_memory(self):
        before_file = Path(self.chain.chain_file).read_bytes()
        before_state = (self.chain.chain.copy(), self.chain.balances.copy(),
                        self.chain.account_nonces.copy(), self.chain.mempool.copy())
        with patch.object(Block, "verify_pow", return_value=True), \
             patch("tensorix.blockchain.chain.os.replace", side_effect=OSError("disk unavailable")):
            with self.assertRaisesRegex(OSError, "disk unavailable"):
                self.chain.submit_block(self.block())
        self.assertEqual(Path(self.chain.chain_file).read_bytes(), before_file)
        self.assertEqual((self.chain.chain, self.chain.balances,
                          self.chain.account_nonces, self.chain.mempool), before_state)
        self.assertEqual([p.name for p in Path(self.directory.name).iterdir()], ["blockchain.json"])

    def test_failed_genesis_write_can_be_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            chain = Blockchain(directory)
            with patch.object(chain, "save_chain", side_effect=OSError("disk unavailable")):
                with self.assertRaises(OSError):
                    chain.submit_block(get_genesis_block())
            self.assertEqual(chain.chain, [])
            self.assertEqual(chain.balances, {})
            self.assertTrue(chain.submit_block(get_genesis_block())[0])


if __name__ == "__main__":
    unittest.main()
