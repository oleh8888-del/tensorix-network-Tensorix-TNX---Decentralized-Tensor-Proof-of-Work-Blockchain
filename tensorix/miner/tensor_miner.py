"""
Tensorix Network (TNX) - CPU Reference Miner
Executes the deterministic NumPy reference hash. No CUDA kernel is implemented here.
"""

import time
import sys
import struct
import httpx
import numpy as np

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# This implementation computes on the CPU, regardless of installed CUDA packages.
GPU_AVAILABLE = False
GPU_COUNT = 0

from ..consensus.crypto import hash256
from ..consensus.tensor_pow import MATRIX_DIM, tensor_pow_hash_cpu

FOUNDER_ADDRESS = "tnx1b050bd6e525ac254ab212efce117cc636eb1166e"
DEV_FEE_PCT = 0.02
DEV_FEE_INTERVAL = 50  # 1 in 50 jobs = 2% Dev Fee -> Founder Wallet


class TensorMiner:
    def __init__(self, node_url: str, payout_address: str, device_id: int = 0, batch_size: int = 128):
        self.node_url = node_url.rstrip("/")
        self.payout_address = payout_address
        self.device_id = device_id
        self.batch_size = batch_size
        self.total_hashes = 0
        self.blocks_found = 0
        self.job_counter = 0
        self.use_gpu = GPU_AVAILABLE

        self.dev_name = "CPU reference (NumPy INT32)"

    def fetch_job(self) -> dict:
        """Fetch latest candidate block template from the node."""
        self.job_counter += 1
        is_dev_fee = (self.job_counter % DEV_FEE_INTERVAL == 0) and (self.payout_address != FOUNDER_ADDRESS)
        target_payout = FOUNDER_ADDRESS if is_dev_fee else self.payout_address
        if is_dev_fee:
            print(f"\n🎁 [Miner Dev Fee 2%] Mining job #{self.job_counter} for Founder Wallet: {FOUNDER_ADDRESS}")

        url = f"{self.node_url}/mining/template?address={target_payout}"
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(url)
                if res.status_code == 200:
                    data = res.json()
                    data["_is_dev_fee"] = is_dev_fee
                    return data
        except Exception as e:
            print(f"[Miner] Failed to connect to node at {self.node_url}: {e}")
        return None

    def submit_solution(self, template: dict, nonce: int) -> bool:
        """Submit solved block to the node."""
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
            with httpx.Client(timeout=10.0) as client:
                res = client.post(url, json=payload)
                if res.status_code == 200:
                    self.blocks_found += 1
                    data = res.json()
                    if template.get("_is_dev_fee"):
                        print(f"\n🎁 [MINER DEV FEE 2%] BLOCK #{template['index']} ACCEPTED!")
                        print(f"Hash: {data.get('block_hash')}")
                        print(f"Dev fee block reward credited directly to Founder Wallet: {FOUNDER_ADDRESS}")
                    else:
                        print(f"\n🎉 [MINER] BLOCK #{template['index']} ACCEPTED BY NODE!")
                        print(f"Hash: {data.get('block_hash')}")
                        print(f"Total Blocks Mined: {self.blocks_found} TNX rewards credited to {self.payout_address}")
                    return True
                else:
                    print(f"\n❌ [MINER] Block rejected: {res.text}")
        except Exception as e:
            print(f"\n❌ [MINER] Error submitting block: {e}")
        return False

    def mine_job_gpu(self, template: dict) -> bool:
        """Mine with the CPU reference implementation (legacy method name)."""
        header_hash = bytes.fromhex(template["header_hash"])
        target = int(template["target"], 16)
        
        # Partition nonce space across GPUs to avoid collision
        stride = max(1, GPU_COUNT)
        start_nonce = self.device_id % stride
        
        last_stat_time = time.time()
        start_t = last_stat_time
        batch_hashes = 0
        
        print(f"\n⛏️ [CPU: {self.dev_name}] Mining Block #{template['index']} | Diff: {template['difficulty']} | Target: {hex(target)[:14]}...")

        nonce = start_nonce
        iteration = 0
        while True:
            # Check if block has been solved or updated every 200 iterations
            if iteration % 200 == 0:
                now = time.time()
                elapsed = now - last_stat_time
                if elapsed >= 3.0:
                    hashrate = batch_hashes / elapsed
                    print(f"[CPU] Speed: {hashrate:.2f} H/s | Nonce: {nonce} | Found: {self.blocks_found}", end="\r")
                    last_stat_time = now
                    batch_hashes = 0
                    
                    # Refresh template check
                    current_job = self.fetch_job()
                    if current_job and current_job["index"] != template["index"]:
                        print(f"\n[CPU] New block detected on network (#{current_job['index']}), switching jobs...")
                        return False

            # Compute Tensor-PoW
            pow_hash = tensor_pow_hash_cpu(header_hash, nonce)
            pow_int = int.from_bytes(pow_hash, "big")
            
            if pow_int <= target:
                elapsed_total = time.time() - start_t
                print(f"\n💎 [CPU] VALID NONCE FOUND: {nonce} in {elapsed_total:.2f}s!")
                return self.submit_solution(template, nonce)

            nonce += stride
            iteration += 1
            batch_hashes += 1
            self.total_hashes += 1

    def start(self):
        print("=" * 65)
        print(f"🚀 TENSORIX CPU REFERENCE MINER (TNX)")
        print(f"Device:         [{self.device_id}] {self.dev_name}")
        print(f"Payout Address: {self.payout_address}")
        print(f"Target Node:    {self.node_url}")
        print("=" * 65)

        while True:
            job = self.fetch_job()
            if not job:
                print(f"[Miner] Waiting for node at {self.node_url}...")
                time.sleep(3)
                continue

            self.mine_job_gpu(job)
            time.sleep(0.5)


if __name__ == "__main__":
    import sys
    node = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8333"
    payout = sys.argv[2] if len(sys.argv) > 2 else "tnx1founder"
    dev = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    miner = TensorMiner(node, payout, device_id=dev)
    miner.start()

