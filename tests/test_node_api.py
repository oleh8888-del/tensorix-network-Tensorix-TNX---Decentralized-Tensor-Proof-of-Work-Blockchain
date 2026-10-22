"""ASGI integration with isolated disk state and the real pinned-genesis proof."""
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from tensorix.node.server import app
from tensorix.genesis import get_genesis_block, GENESIS_HASH

MINER = "tnx1" + "a" * 40


class NodeApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.environment = patch.dict(os.environ, {"TENSORIX_DATA_DIR": self.directory.name})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.client = self.enterContext(TestClient(app))

    def initialize(self):
        response = self.client.post("/mining/submit", json=get_genesis_block().to_dict())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["block_hash"], GENESIS_HASH)

    def test_real_genesis_submission_persists_across_startup(self):
        self.assertEqual(self.client.get("/info").json()["status"], "uninitialized")
        self.initialize()
        self.assertEqual(self.client.get("/block/latest").json()["hash"], GENESIS_HASH)
        with TestClient(app) as reloaded:
            self.assertEqual(reloaded.get("/info").json()["latest_block_hash"], GENESIS_HASH)

    def test_payout_template_discloses_exact_onchain_split(self):
        self.initialize()
        response = self.client.get("/mining/template", params={"address": MINER})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["miner_reward_tnx"], 9.8)
        self.assertEqual(body["pool_fee_tnx"], .2)
        self.assertEqual(body["transactions"][0]["recipient"], MINER)

    def test_invalid_payout_and_out_of_range_nonce_are_rejected(self):
        self.initialize()
        self.assertEqual(self.client.get("/mining/template", params={"address": "tnx1fake"}).status_code, 400)
        invalid = get_genesis_block().to_dict() | {"nonce": 2**64}
        self.assertEqual(self.client.post("/mining/submit", json=invalid).status_code, 400)
        self.assertEqual(self.client.get("/block/latest").json()["hash"], GENESIS_HASH)

    def test_explorer_and_api_label_experimental_status(self):
        self.assertEqual(self.client.get("/api").json()["status"], "experimental")
        body = self.client.get("/").text
        self.assertIn("EXPERIMENTAL REFERENCE", body)
        self.assertNotIn("MAINNET ONLINE", body)


if __name__ == "__main__":
    unittest.main()
