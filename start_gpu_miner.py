"""Launch Tensorix GPU miner with an explicit public payout address."""
import argparse
from tensorix.blockchain.transaction import valid_address
from tensorix.miner.cuda_miner import CudaMiner


def main():
    p = argparse.ArgumentParser(description='Tensorix experimental NVIDIA CUDA miner')
    p.add_argument('--address', required=True, help='Complete public TNX payout address')
    p.add_argument('--node', default='https://tensorix-network.leafyshark16.chatgpt.site/rpc')
    p.add_argument('--device', type=int, default=0)
    p.add_argument('--batch-size', type=int, default=64)
    a = p.parse_args()
    if not valid_address(a.address):
        p.error('Complete TNX payout address required')
    if not a.node.startswith(('https://', 'http://127.0.0.1:', 'http://localhost:')):
        p.error('Use an HTTPS node or loopback HTTP endpoint')
    try:
        CudaMiner(a.node, a.address, a.device, a.batch_size).start()
    except (RuntimeError, ValueError) as exc:
        p.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
