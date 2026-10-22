"""
Tensorix Network (TNX) - Stratum Mining Pool Server
Provides a Tensorix-specific Stratum-like solo relay and HTTP stats.
Compatibility with generic Bitcoin Stratum V1 miners is not established.
"""

import sys
import os
import json
import time
import asyncio
import httpx
from typing import Dict, Set
from collections import OrderedDict
from ..blockchain.transaction import valid_address

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from ..consensus.tensor_pow import tensor_pow_hash_cpu, difficulty_to_target, MAX_TARGET

DEFAULT_NODE_URL = "http://127.0.0.1:8333"
DEFAULT_STRATUM_PORT = 3333
DEFAULT_SHARE_DIFF = 1.0  # Match the network's minimum supported target.
FOUNDER_ADDRESS = "tnx1b050bd6e525ac254ab212efce117cc636eb1166e"
POOL_FEE_PCT = 0.02       # 2% Mining Pool fee -> Founder Wallet


class StratumClient:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, client_id: str):
        self.reader = reader
        self.writer = writer
        self.client_id = client_id
        self.worker_name = "unknown"
        self.payout_address = ""
        self.authorized = False
        self.shares = 0
        self.blocks = 0
        self.last_share_time = time.time()
        self.hashrate = None
        self.jobs = OrderedDict()
        self.seen_nonces = OrderedDict()

    async def send_json(self, data: dict):
        line = json.dumps(data) + "\n"
        self.writer.write(line.encode("utf-8"))
        await self.writer.drain()


class StratumServer:
    def __init__(self, node_url: str = DEFAULT_NODE_URL, port: int = DEFAULT_STRATUM_PORT, default_payout: str = ""):
        self.node_url = node_url.rstrip("/")
        self.port = port
        self.default_payout = default_payout
        self.clients: Dict[str, StratumClient] = {}
        self.current_template: dict = {}
        self.total_pool_shares = 0
        self.total_blocks_found = 0
        self.job_counter = 0

    async def fetch_template(self, address: str = "") -> dict:
        """Fetch latest block template from local Tensorix node."""
        if not address:
            auth_clients = [c for c in self.clients.values() if c.authorized and c.payout_address.startswith("tnx1")]
            if auth_clients:
                addr = auth_clients[0].payout_address
            else:
                addr = self.default_payout or FOUNDER_ADDRESS
        else:
            addr = address

        url = f"{self.node_url}/mining/template?address={addr}"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    return res.json()
        except Exception as e:
            print(f"[Stratum Pool] Error contacting node: {e}")
        return {}

    async def submit_block_to_node(self, template: dict, nonce: int) -> bool:
        url = f"{self.node_url}/mining/submit"
        payload = {
            "index": template["index"],
            "prev_hash": template["prev_hash"],
            "timestamp": template["timestamp"],
            "difficulty": template["difficulty"],
            "nonce": nonce,
            "merkle_root": template["merkle_root"],
            "transactions": template["transactions"]
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    self.total_blocks_found += 1
                    print(f"\n🎉 [STRATUM POOL] BLOCK #{template['index']} FOUND BY POOL MINER! Subsidies credited.")
                    return True
                else:
                    print(f"\n❌ [STRATUM POOL] Node rejected block: {res.text}")
        except Exception as e:
            print(f"[STRATUM POOL] Error submitting block: {e}")
        return False

    async def notify_miner(self, client, clean_jobs=False):
        template = await self.fetch_template(client.payout_address)
        if not template:
            return False
        rewards = [tx for tx in template.get("transactions", []) if tx.get("sender") == "COINBASE"]
        if not rewards or rewards[0].get("recipient") != client.payout_address:
            return False
        self.job_counter += 1
        job_id = f"job_{self.job_counter}"
        if clean_jobs:
            client.jobs.clear()
        client.jobs[job_id] = template
        while len(client.jobs) > 16:
            client.jobs.popitem(last=False)
        await client.send_json({"id": None, "method": "mining.notify", "params": [
            job_id, template["header_hash"], template["target"], clean_jobs]})
        return True

    async def notify_all_miners(self, clean_jobs=False):
        for client in list(self.clients.values()):
            if client.authorized:
                try:
                    await self.notify_miner(client, clean_jobs)
                except (ConnectionError, OSError):
                    pass

    async def submit_share(self, client, message_id, params):
        async def reject(code, reason):
            await client.send_json({"id": message_id, "result": False, "error": [code, reason, None]})
        if not client.authorized:
            return await reject(24, "Authorization required")
        if not isinstance(params, list) or len(params) < 3 or params[0] != client.worker_name:
            return await reject(20, "Invalid worker or submit parameters")
        job_id = params[1]
        if not isinstance(job_id, str) or job_id not in client.jobs:
            return await reject(21, "Unknown or stale job")
        template = client.jobs[job_id]
        if self.current_template and template["prev_hash"] != self.current_template["prev_hash"]:
            return await reject(21, "Stale parent block")
        raw_nonce = params[4] if len(params) >= 5 else params[2]
        try:
            if type(raw_nonce) is int:
                nonce = raw_nonce
            elif isinstance(raw_nonce, str) and 1 <= len(raw_nonce) <= 16:
                nonce = int(raw_nonce, 16)
            else:
                raise ValueError("Invalid nonce")
            if not 0 <= nonce < 2**64:
                raise ValueError("Nonce outside uint64")
        except (ValueError, TypeError):
            return await reject(20, "Invalid nonce")
        key = (job_id, nonce)
        if key in client.seen_nonces:
            return await reject(22, "Duplicate share")
        try:
            header = bytes.fromhex(template["header_hash"])
            net_target = int(template["target"], 16)
            if len(header) != 32 or not 0 < net_target <= MAX_TARGET:
                raise ValueError("Invalid template")
            proof = await asyncio.to_thread(tensor_pow_hash_cpu, header, nonce)
            value = int.from_bytes(proof, "big")
        except (ValueError, TypeError, OverflowError):
            return await reject(20, "Invalid work")
        if value > difficulty_to_target(DEFAULT_SHARE_DIFF):
            return await reject(23, "Low difficulty share")
        found_block = value <= net_target
        if found_block and not await self.submit_block_to_node(template, nonce):
            return await reject(23, "Block not accepted by node")
        client.seen_nonces[key] = None
        while len(client.seen_nonces) > 8192:
            client.seen_nonces.popitem(last=False)
        client.shares += 1
        self.total_pool_shares += 1
        client.last_share_time = time.time()
        if found_block:
            client.blocks += 1
        await client.send_json({"id": message_id, "result": True, "error": None})
        if found_block:
            latest = await self.fetch_template(client.payout_address)
            if latest:
                self.current_template = latest
                await self.notify_all_miners(clean_jobs=True)

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr_info = writer.get_extra_info("peername")
        client_id = f"{addr_info[0]}:{addr_info[1]}"
        client = StratumClient(reader, writer, client_id)
        self.clients[client_id] = client
        print(f"[Stratum Pool] New miner connected from {client_id}")

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break

                # If connection sent HTTP GET request (web browser view)
                if line.startswith(b"GET ") or line.startswith(b"POST "):
                    # Handle lightweight HTTP dashboard
                    stats_body = json.dumps({
                        "pool": "Tensorix experimental solo Stratum relay",
                        "status": "online",
                        "pool_fee": "2%",
                        "pool_fee_recipient": FOUNDER_ADDRESS,
                        "payout_model": "98% Miner / 2% Founder on-chain split",
                        "stratum_port": self.port,
                        "active_miners": len([c for c in self.clients.values() if c.authorized]),
                        "total_shares": self.total_pool_shares,
                        "total_blocks_found": self.total_blocks_found,
                        "current_block_index": self.current_template.get("index", 0),
                        "network_difficulty": self.current_template.get("difficulty", 1.0),
                        "miners": [
                            {"client": c.client_id, "worker": c.worker_name, "payout": c.payout_address, "shares": c.shares}
                            for c in self.clients.values() if c.authorized
                        ]
                    }, indent=2)
                    http_resp = (
                        "HTTP/1.1 200 OK\r\n"
                        "Content-Type: application/json; charset=utf-8\r\n"
                        f"Content-Length: {len(stats_body.encode('utf-8'))}\r\n"
                        "Access-Control-Allow-Origin: *\r\n"
                        "\r\n" + stats_body
                    )
                    writer.write(http_resp.encode("utf-8"))
                    await writer.drain()
                    break

                try:
                    msg = json.loads(line.decode("utf-8"))
                except Exception:
                    continue

                msg_id = msg.get("id")
                method = msg.get("method")
                params = msg.get("params", [])

                if method == "mining.subscribe":
                    # Reply with subscription details
                    extranonce1 = "0100"
                    res = [
                        [
                            ["mining.set_difficulty", "sub_diff"],
                            ["mining.notify", "sub_notify"]
                        ],
                        extranonce1,
                        4
                    ]
                    await client.send_json({"id": msg_id, "result": res, "error": None})
                    # Set client share difficulty
                    await client.send_json({"id": None, "method": "mining.set_difficulty", "params": [DEFAULT_SHARE_DIFF]})

                elif method == "mining.authorize":
                    username = params[0] if params and isinstance(params[0], str) else ""
                    payout = username.split(".")[0]
                    if not valid_address(payout):
                        await client.send_json({"id": msg_id, "result": False, "error": [24, "Complete TNX payout address required", None]})
                        continue
                    client.worker_name = username
                    client.payout_address = payout
                    client.authorized = True
                    await client.send_json({"id": msg_id, "result": True, "error": None})
                    await self.notify_miner(client, clean_jobs=True)

                elif method == "mining.submit":
                    await self.submit_share(client, msg_id, params)

                elif method == "mining.get_transactions":
                    await client.send_json({"id": msg_id, "result": [], "error": None})
                else:
                    await client.send_json({"id": msg_id, "result": None, "error": [20, "Method not supported", None]})

        except Exception as e:
            print(f"[Stratum Pool] Client {client_id} disconnected: {e}")
        finally:
            self.clients.pop(client_id, None)
            writer.close()

    async def template_poll_loop(self):
        """Polls node for new blocks / templates every 3 seconds."""
        last_index = -1
        while True:
            tmpl = await self.fetch_template()
            if tmpl and tmpl.get("index") != last_index:
                print(f"[Stratum Pool] New network job #{tmpl['index']} | Difficulty: {tmpl['difficulty']:.2f}")
                self.current_template = tmpl
                last_index = tmpl["index"]
                await self.notify_all_miners(clean_jobs=True)
            await asyncio.sleep(3)

    async def start(self):
        print("=" * 65)
        print("⚡ TENSORIX STRATUM MINING POOL SERVER (TNX)")
        print(f"Stratum Port:   tcp://0.0.0.0:{self.port}")
        print(f"Pool Dashboard: http://127.0.0.1:{self.port}/")
        print(f"Node RPC:       {self.node_url}")
        print("=" * 65)

        # Initial fetch
        self.current_template = await self.fetch_template()

        server = await asyncio.start_server(self.handle_client, os.environ.get("TENSORIX_STRATUM_HOST", "127.0.0.1"), self.port)
        asyncio.create_task(self.template_poll_loop())

        async with server:
            await server.serve_forever()


def main():
    port = int(os.environ.get("STRATUM_PORT", DEFAULT_STRATUM_PORT))
    node_url = os.environ.get("TENSORIX_NODE", DEFAULT_NODE_URL)
    pool = StratumServer(node_url=node_url, port=port)
    asyncio.run(pool.start())


if __name__ == "__main__":
    main()

