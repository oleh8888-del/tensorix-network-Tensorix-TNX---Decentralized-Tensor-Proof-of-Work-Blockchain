"""Prevent hidden template redirection on top of the consensus subsidy split."""
import unittest
from unittest.mock import patch
import httpx
from tensorix.miner.tensor_miner import TensorMiner
from tensorix.miner.cuda_miner import CudaMiner

PAYOUT = "tnx1" + "a" * 40

class SingleMiningFeeTests(unittest.TestCase):
    def check_requests(self, factory, sessions, requests_per_session):
        seen = []
        original_client = httpx.Client
        def respond(request):
            seen.append(request.url.params.get("address"))
            return httpx.Response(200, json={"index": 92, "prev_hash": "0" * 64})
        def client(**kwargs):
            return original_client(transport=httpx.MockTransport(respond), **kwargs)
        with patch("tensorix.miner.tensor_miner.httpx.Client", side_effect=client):
            for _ in range(sessions):
                miner = factory()
                for _ in range(requests_per_session):
                    job = miner.fetch_job()
                    self.assertIsNotNone(job)
                    self.assertIs(job["_is_dev_fee"], False)
        self.assertEqual(len(seen), sessions * requests_per_session)
        self.assertEqual(set(seen), {PAYOUT})

    def test_cpu_reference_keeps_payout_at_50th_100th_and_150th_requests(self):
        self.check_requests(lambda: TensorMiner("http://node.test", PAYOUT), 1, 150)

    def test_gpu_inherited_fetch_never_redirects_work(self):
        def gpu_without_hardware():
            miner = CudaMiner.__new__(CudaMiner)
            TensorMiner.__init__(miner, "http://node.test", PAYOUT)
            return miner
        self.check_requests(gpu_without_hardware, 1, 150)

    def test_restarts_do_not_introduce_an_additional_mining_fee(self):
        self.check_requests(lambda: TensorMiner("http://node.test", PAYOUT), 3, 51)
