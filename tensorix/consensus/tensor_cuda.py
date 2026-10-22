"""Full GPU Tensor-PoW: BLAKE3 CUDA stages and INT8 Tensor Core matrix rounds.

No CPU hash or ordinary-CUDA matrix fallback exists. The CPU reference is
kept separately for independent node verification and consensus tests.
"""
import numpy as np
from .tensor_cuda_hash import BLAKE3_CUDA_SOURCE

CUDA_SOURCE = r'''
// PTX operand mapping follows NVIDIA PTX ISA, MMA m16n8k32 integer fragments.
__device__ __forceinline__ unsigned int left_word(const void* src, int batch, int row, int col, bool reduce) {
    unsigned int packed = 0;
    #pragma unroll
    for (int j = 0; j < 4; ++j) {
        int pos = batch*4096 + row*64 + col+j;
        int value;
        if (reduce) {
            value = ((const int*)src)[pos] % 127;
            if (value < 0) value += 127;
        } else value = ((const signed char*)src)[pos];
        packed |= (unsigned int)(unsigned char)value << (8*j);
    }
    return packed;
}
__device__ __forceinline__ unsigned int right_word(const signed char* src, int batch, int row, int col) {
    unsigned int packed = 0;
    #pragma unroll
    for (int j = 0; j < 4; ++j)
        packed |= (unsigned int)(unsigned char)src[batch*4096+(row+j)*64+col] << (8*j);
    return packed;
}
__device__ __forceinline__ void tensor_round(const void* left, const signed char* right, int* out, bool reduce) {
    const int batch = blockIdx.z, tile_row = blockIdx.x*16, tile_col = blockIdx.y*8;
    const int group = threadIdx.x >> 2, thread = threadIdx.x & 3;
    int c0=0, c1=0, c2=0, c3=0;
    #pragma unroll
    for (int k = 0; k < 64; k += 32) {
        unsigned int a0 = left_word(left,batch,tile_row+group,k+thread*4,reduce);
        unsigned int a1 = left_word(left,batch,tile_row+group+8,k+thread*4,reduce);
        unsigned int a2 = left_word(left,batch,tile_row+group,k+thread*4+16,reduce);
        unsigned int a3 = left_word(left,batch,tile_row+group+8,k+thread*4+16,reduce);
        unsigned int b0 = right_word(right,batch,k+thread*4,tile_col+group);
        unsigned int b1 = right_word(right,batch,k+thread*4+16,tile_col+group);
        asm volatile(
            "mma.sync.aligned.m16n8k32.row.col.s32.s8.s8.s32 "
            "{%0,%1,%2,%3}, {%4,%5,%6,%7}, {%8,%9}, {%0,%1,%2,%3};"
            : "+r"(c0), "+r"(c1), "+r"(c2), "+r"(c3)
            : "r"(a0), "r"(a1), "r"(a2), "r"(a3), "r"(b0), "r"(b1));
    }
    int pos = batch*4096+(tile_row+group)*64+tile_col+thread*2;
    out[pos]=c0; out[pos+1]=c1; out[pos+8*64]=c2; out[pos+8*64+1]=c3;
}
extern "C" __global__ void round_one(const signed char* a, const signed char* b, int* c) {
    tensor_round(a, b, c, false);
}
extern "C" __global__ void round_two(const int* c, const signed char* d, int* out) {
    tensor_round(c, d, out, true);
}
'''





class TensorCudaBackend:
    def __init__(self, device: int = 0):
        try:
            import cupy as cp
        except ImportError as exc:
            raise RuntimeError('GPU miner requires CuPy for your installed CUDA runtime') from exc
        self.cp = cp
        options = ('--std=c++17',)
        count = cp.cuda.runtime.getDeviceCount()
        if type(device) is not int or not 0 <= device < count:
            raise ValueError('NVIDIA CUDA device index is outside the available devices')
        self.device = device
        self.device_count = count
        with cp.cuda.Device(device):
            props = cp.cuda.runtime.getDeviceProperties(device)
            if props['major'] < 8:
                raise RuntimeError('This experimental build requires NVIDIA compute capability 8.0 or newer')
            self.name = props['name'].decode() if isinstance(props['name'], bytes) else props['name']
            self.module = cp.RawModule(code=CUDA_SOURCE + BLAKE3_CUDA_SOURCE, options=options)
            self.first = self.module.get_function('round_one')
            self.second = self.module.get_function('round_two')
            self.seed_kernel = self.module.get_function('make_seeds')
            self.expand_kernel = self.module.get_function('expand_matrices')
            self.expand_second_kernel = self.module.get_function('expand_second')
            self.hash_matrix_kernel = self.module.get_function('hash_matrix')
        self.gpu_rounds = 0

    def hash_batch(self, header: bytes, nonces: list[int]) -> list[bytes]:
        if not isinstance(header, bytes) or len(header) != 32:
            raise ValueError('Tensor-PoW header must be exactly 32 bytes')
        if not isinstance(nonces, list) or not 1 <= len(nonces) <= 1024:
            raise ValueError('A CUDA batch must contain between 1 and 1024 nonces')
        if any(type(n) is not int or not 0 <= n < 2**64 for n in nonces):
            raise ValueError('Every nonce must be uint64')
        cp = self.cp
        count = len(nonces)
        with cp.cuda.Device(self.device):
            gpu_header = cp.asarray(np.frombuffer(header, dtype='<u4'))
            gpu_nonces = cp.asarray(np.asarray(nonces, dtype=np.uint64))
            seeds = cp.empty((count, 8), dtype=cp.uint32)
            a = cp.empty((count, 4096), dtype=cp.int8)
            b = cp.empty_like(a)
            c = cp.empty((count, 4096), dtype=cp.int32)
            middle = cp.empty_like(seeds)
            d = cp.empty_like(a)
            final = cp.empty_like(c)
            proofs = cp.empty_like(seeds)
            self.seed_kernel(((count+127)//128,), (128,), (gpu_header, gpu_nonces, seeds, np.int32(count)))
            self.expand_kernel(((count*256+127)//128,), (128,), (seeds, a, b, np.int32(count)))
            self.first((4, 8, count), (32,), (a, b, c))
            self.hash_matrix_kernel((count,), (32,), (seeds, c, middle))
            self.expand_second_kernel(((count*128+127)//128,), (128,), (middle, d, np.int32(count)))
            self.second((4, 8, count), (32,), (c, d, final))
            self.hash_matrix_kernel((count,), (32,), (middle, final, proofs))
            host = cp.asnumpy(proofs).astype('<u4', copy=False)
            cp.cuda.get_current_stream().synchronize()
        self.gpu_rounds += 2 * count
        return [row.tobytes() for row in host]
