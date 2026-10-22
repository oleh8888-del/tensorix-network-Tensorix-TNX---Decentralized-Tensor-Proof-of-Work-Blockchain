"""Per-worker payout and honest Stratum share-accounting regressions."""
import unittest
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tensorix.miner.stratum_server import StratumServer
from tensorix.consensus.tensor_pow import MAX_TARGET


def client(address):
    return SimpleNamespace(payout_address=address, authorized=True,
        worker_name=address + ".rig", jobs=OrderedDict(), seen_nonces=OrderedDict(),
        send_json=AsyncMock(), shares=0, blocks=0, last_share_time=0)


def template(address):
    return {"index": 1, "prev_hash": "a" * 64, "header_hash": ("11" if address.endswith("1") else "22") * 32,
        "target": hex(MAX_TARGET // 4), "transactions": [
        {"sender": "COINBASE", "recipient": address, "amount": 980000000}]}


class StratumTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = StratumServer()
        self.a = client("tnx1" + "1" * 40)
        self.b = client("tnx1" + "2" * 40)
        self.server.clients = {"a": self.a, "b": self.b}
        self.server.fetch_template = AsyncMock(side_effect=lambda address: template(address))
        self.server.submit_block_to_node = AsyncMock(return_value=True)

    async def test_each_worker_receives_its_own_payout_template(self):
        await self.server.notify_all_miners(True)
        a = next(iter(self.a.jobs.values()))
        b = next(iter(self.b.jobs.values()))
        self.assertEqual(a["transactions"][0]["recipient"], self.a.payout_address)
        self.assertEqual(b["transactions"][0]["recipient"], self.b.payout_address)
        self.assertNotEqual(a["header_hash"], b["header_hash"])

    async def test_missing_job_is_rejected_without_credit(self):
        await self.server.submit_share(self.a, 1, [self.a.worker_name, "missing", 0])
        self.assertEqual(self.a.shares, 0)
        self.assertFalse(self.a.send_json.call_args.args[0]["result"])

    async def test_other_worker_cannot_use_an_issued_job(self):
        await self.server.notify_miner(self.a)
        job = next(iter(self.a.jobs))
        await self.server.submit_share(self.b, 1, [self.b.worker_name, job, 0])
        self.assertEqual(self.server.total_pool_shares, 0)
        self.assertFalse(self.b.send_json.call_args.args[0]["result"])

    async def test_unauthorized_submit_is_rejected(self):
        self.a.authorized = False
        await self.server.submit_share(self.a, 1, [self.a.worker_name, "job", 0])
        self.assertFalse(self.a.send_json.call_args.args[0]["result"])
        self.assertEqual(self.server.total_pool_shares, 0)

    async def test_bad_nonce_never_becomes_zero(self):
        await self.server.notify_miner(self.a)
        job = next(iter(self.a.jobs))
        with patch("tensorix.miner.stratum_server.tensor_pow_hash_cpu") as hashing:
            await self.server.submit_share(self.a, 1, [self.a.worker_name, job, "invalid"])
            hashing.assert_not_called()
        self.assertFalse(self.a.send_json.call_args.args[0]["result"])

    async def test_invalid_proof_does_not_inflate_share_count(self):
        await self.server.notify_miner(self.a)
        job = next(iter(self.a.jobs))
        with patch("tensorix.miner.stratum_server.tensor_pow_hash_cpu", return_value=b"\xff" * 32):
            await self.server.submit_share(self.a, 1, [self.a.worker_name, job, 0])
        self.assertEqual(self.a.shares, 0)
        self.assertFalse(self.a.send_json.call_args.args[0]["result"])

    async def test_valid_pool_share_is_credited_once(self):
        await self.server.notify_miner(self.a)
        job = next(iter(self.a.jobs))
        proof = (MAX_TARGET // 2).to_bytes(32, "big")
        with patch("tensorix.miner.stratum_server.tensor_pow_hash_cpu", return_value=proof) as hashing:
            params = [self.a.worker_name, job, "unused", "unused", "00000010"]
            await self.server.submit_share(self.a, 1, params)
            self.assertTrue(self.a.send_json.call_args.args[0]["result"])
            self.assertEqual(hashing.call_args.args[1], 16)
            await self.server.submit_share(self.a, 2, params)
        self.assertEqual(self.a.shares, 1)
        self.assertEqual(self.server.total_pool_shares, 1)
        self.assertFalse(self.a.send_json.call_args.args[0]["result"])

    async def test_node_rejected_block_is_not_acknowledged_or_credited(self):
        await self.server.notify_miner(self.a)
        job = next(iter(self.a.jobs))
        self.server.submit_block_to_node.return_value = False
        with patch("tensorix.miner.stratum_server.tensor_pow_hash_cpu", return_value=b"\x00" * 32):
            await self.server.submit_share(self.a, 1, [self.a.worker_name, job, 0])
        self.assertEqual(self.a.blocks, 0)
        self.assertEqual(self.a.shares, 0)
        self.assertFalse(self.a.send_json.call_args.args[0]["result"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
