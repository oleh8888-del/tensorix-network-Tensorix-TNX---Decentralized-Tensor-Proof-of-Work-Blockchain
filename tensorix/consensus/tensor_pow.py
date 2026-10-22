"""
Tensorix Network (TNX) - Tensor Proof-of-Work (Tensor-PoW) Consensus
NumPy CPU reference using integer matrix multiplications.
No CUDA or Tensor Core kernel is implemented in this module.
"""

import struct
import math
import numpy as np
from .crypto import hash256, hash256_hex

# Constant: Maximum 256-bit target (Difficulty = 1)
# 12 leading zero bits for fast bootstrap / genesis mining, LWMA scales it smoothly
MAX_TARGET = 0x000fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
MATRIX_DIM = 64  # 64x64 matrices (4096 elements per matrix)


def difficulty_to_target(difficulty: float) -> int:
    """Convert difficulty multiplier to integer 256-bit target."""
    if not math.isfinite(difficulty) or difficulty < 1:
        raise ValueError("Network difficulty must be finite and at least one")
    target = int(MAX_TARGET / difficulty)
    return max(1, min(target, MAX_TARGET))


def target_to_difficulty(target: int) -> float:
    """Convert integer target back to human-readable difficulty."""
    if target <= 0:
        return 1.0
    return float(MAX_TARGET / target)


def tensor_pow_hash_cpu(header_hash: bytes, nonce: int) -> bytes:
    """
    Deterministic CPU implementation of Tensor-PoW used for node block validation.
    
    Algorithm:
    1. Seed the hash expansion with mandatory BLAKE3(header_hash || nonce).
    2. Expand pseudo-random bytes into two 64x64 signed 8-bit integer matrices A and B.
    3. Perform matrix multiplication: C = A * B (32-bit integer accumulation).
    4. Fold C into an intermediate 32-byte digest, mix with original seed, and repeat round 2.
    5. Final 256-bit hash is BLAKE3 of the combined matrix outputs.
    """
    # Round 1: Generate initial seed
    seed = hash256(header_hash + struct.pack("<Q", nonce))
    
    # Expand 32-byte seed into 8192 bytes for two 64x64 matrices A and B
    # Using deterministic ChaCha20/Hash-based stream expansion
    expanded = bytearray()
    counter = 0
    while len(expanded) < (MATRIX_DIM * MATRIX_DIM * 2):
        counter_bytes = struct.pack("<I", counter)
        expanded.extend(hash256(seed + counter_bytes))
        counter += 1
        
    raw_data = np.frombuffer(bytes(expanded[:MATRIX_DIM * MATRIX_DIM * 2]), dtype=np.int8)
    mat_a = raw_data[:MATRIX_DIM * MATRIX_DIM].reshape((MATRIX_DIM, MATRIX_DIM))
    mat_b = raw_data[MATRIX_DIM * MATRIX_DIM:].reshape((MATRIX_DIM, MATRIX_DIM))
    
    # Tensor operation: INT8 x INT8 -> INT32 Matrix Multiplication
    mat_c = np.matmul(mat_a.astype(np.int32), mat_b.astype(np.int32))
    
    # Round 2: Mix round 1 output with seed to generate permutation matrix
    mid_hash = hash256(seed + mat_c.astype("<i4", copy=False).tobytes())
    expanded_r2 = bytearray()
    counter = 0
    while len(expanded_r2) < (MATRIX_DIM * MATRIX_DIM):
        counter_bytes = struct.pack("<I", counter + 1000)
        expanded_r2.extend(hash256(mid_hash + counter_bytes))
        counter += 1
        
    mat_d = np.frombuffer(bytes(expanded_r2[:MATRIX_DIM * MATRIX_DIM]), dtype=np.int8).reshape((MATRIX_DIM, MATRIX_DIM))
    
    # Second Tensor core pass: Matmul with transformed matrix
    final_mat = np.matmul((mat_c % 127).astype(np.int8).astype(np.int32), mat_d.astype(np.int32))
    
    # Final 256-bit hash
    final_pow_hash = hash256(mid_hash + final_mat.astype("<i4", copy=False).tobytes())
    return final_pow_hash


def verify_pow(header_hash: bytes, nonce: int, target: int) -> bool:
    """Verify that a given nonce produces a Tensor-PoW hash <= target."""
    pow_hash = tensor_pow_hash_cpu(header_hash, nonce)
    hash_int = int.from_bytes(pow_hash, byteorder="big")
    return hash_int <= target

