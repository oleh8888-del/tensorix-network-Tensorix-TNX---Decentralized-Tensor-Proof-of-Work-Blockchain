"""Tensorix experimental GPU miner: INT8 Tensor Core matrix rounds and GPU BLAKE3."""
import time
from ..consensus.tensor_cuda import TensorCudaBackend
from .tensor_miner import TensorMiner


class CudaMiner(TensorMiner):
    def __init__(self, node_url, payout_address, device_id=0, batch_size=64):
        super().__init__(node_url, payout_address, device_id, batch_size)
        if type(batch_size) is not int or not 1 <= batch_size <= 1024:
            raise ValueError('Batch size must be between 1 and 1024')
        self.backend = TensorCudaBackend(device_id)
        self.dev_name = self.backend.name
        self.use_gpu = True

    def mine_job_gpu(self, template):
        header = bytes.fromhex(template['header_hash'])
        target = int(template['target'], 16)
        stride = self.backend.device_count
        nonce = self.device_id
        last_poll = last_report = time.monotonic()
        previous_hashes = self.total_hashes
        print(f'[CUDA {self.device_id}] Block #{template["index"]}, {self.dev_name}')
        while nonce < 2**64:
            count = min(self.batch_size, (2**64 - 1 - nonce) // stride + 1)
            nonces = [nonce + i * stride for i in range(count)]
            hashes = self.backend.hash_batch(header, nonces)
            self.total_hashes += count
            for candidate, proof in zip(nonces, hashes):
                if int.from_bytes(proof, 'big') <= target:
                    print(f'[CUDA {self.device_id}] Valid proof, nonce={candidate}, hash={proof.hex()}')
                    return self.submit_solution(template, candidate)
            nonce += count * stride
            now = time.monotonic()
            if now - last_report >= 5:
                rate = (self.total_hashes - previous_hashes) / (now - last_report)
                print(f'[CUDA {self.device_id}] {rate:.2f} H/s, {self.total_hashes} hashes')
                last_report, previous_hashes = now, self.total_hashes
            if now - last_poll >= 3:
                current = self.fetch_job()
                if current and (current['index'] != template['index'] or current['prev_hash'] != template['prev_hash']):
                    return False
                last_poll = now
        return False

    def start(self):
        print(f'TENSORIX GPU CUDA MINER — {self.dev_name} (device {self.device_id})')
        print('INT8 Tensor Core matrix rounds; BLAKE3 also executes on the GPU.')
        print('On-chain subsidy split: 98% miner / 2% founder.')
        print('Additional legacy dev scheduler retained; it does not guarantee 2% of work. See AUDIT.md.')
        while True:
            job = self.fetch_job()
            if job:
                self.mine_job_gpu(job)
            else:
                print(f'Waiting for node {self.node_url}')
                time.sleep(3)
            time.sleep(.5)
