"""
Tensorix Network (TNX) - CPU Reference Miner Launcher
"""

import sys
import os
from tensorix.miner.tensor_miner import TensorMiner, GPU_AVAILABLE, GPU_COUNT
from tensorix.wallet.wallet_cli import load_wallet
from tensorix.blockchain.transaction import valid_address

def main():
    wallet_file = "founder_wallet.json"
    if not os.path.exists(wallet_file):
        wallet_file = "tensorix_wallet.json"

    if os.path.exists(wallet_file):
        wallet = load_wallet(wallet_file)
        miner_addr = wallet["address"]
    else:
        miner_addr = ""

    dev_id = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    node_url = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8333"
    if len(sys.argv) > 3:
        miner_addr = sys.argv[3]

    print("=" * 60)
    print("⚡ TENSORIX CPU REFERENCE MINER")
    print(f"CUDA GPUs Detected: {GPU_COUNT}")
    print(f"Target GPU Device:  [{dev_id}]")
    print(f"Payout Address:     {miner_addr}")
    print(f"Node Address:       {node_url}")
    print("=" * 60)

    miner = TensorMiner(node_url=node_url, payout_address=miner_addr, device_id=dev_id)
    miner.start()

if __name__ == "__main__":
    main()

