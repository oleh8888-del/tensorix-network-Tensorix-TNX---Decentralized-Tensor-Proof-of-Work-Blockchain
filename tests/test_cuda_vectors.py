"""Run explicitly on a CUDA host; skip on ordinary CPU CI environments."""
import os
import unittest
from tensorix.consensus.tensor_pow import tensor_pow_hash_cpu


@unittest.skipUnless(os.environ.get('TENSORIX_TEST_CUDA') == '1', 'CUDA host opt-in required')
class CudaConsensusVectors(unittest.TestCase):
    def test_historical_public_proofs_match_on_every_device(self):
        import json
        from pathlib import Path
        import cupy as cp
        from tensorix.blockchain.block import Block
        from tensorix.consensus.tensor_pow import difficulty_to_target
        from tensorix.consensus.tensor_cuda import TensorCudaBackend
        fixture = json.loads((Path(__file__).parent / 'fixtures/legacy-blocks-0-2.json').read_text())
        for device in range(cp.cuda.runtime.getDeviceCount()):
            backend = TensorCudaBackend(device)
            for index in [0, 2]:
                block = Block.from_dict(fixture[index])
                proof = backend.hash_batch(block.header_bytes(), [block.nonce])[0]
                self.assertEqual(proof.hex(), block.hash)
                self.assertLessEqual(int.from_bytes(proof, 'big'), difficulty_to_target(block.difficulty))

    def test_real_devices_match_cpu_consensus(self):
        import cupy as cp
        from tensorix.consensus.tensor_cuda import TensorCudaBackend
        vectors = [(bytes(32), [0, 1, 255, 2**32, 2**64 - 1]),
                   (bytes(range(32)), [7, 127, 65535]),
                   (bytes.fromhex('ff' * 32), [42, 9223372036854775808])]
        for device in range(cp.cuda.runtime.getDeviceCount()):
            backend = TensorCudaBackend(device)
            for header, nonces in vectors:
                with self.subTest(device=device, header=header.hex()):
                    self.assertEqual(backend.hash_batch(header, nonces),
                                     [tensor_pow_hash_cpu(header, n) for n in nonces])
            self.assertEqual(backend.gpu_rounds, 20)
            with self.assertRaises(ValueError): backend.hash_batch(bytes(31), [0])
            with self.assertRaises(ValueError): backend.hash_batch(bytes(32), [-1])
            with self.assertRaises(ValueError): backend.hash_batch(bytes(32), [2**64])
            with self.assertRaises(ValueError): backend.hash_batch(bytes(32), [True])
