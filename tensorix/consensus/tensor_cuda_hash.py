"""Fixed-length BLAKE3 GPU stages for the existing Tensorix PoW contract.

Only unkeyed 32-byte output is implemented. Input lengths are 36, 40 and
16416 bytes; this is not a general-purpose BLAKE3 library.
"""

BLAKE3_CUDA_SOURCE = r'''
__device__ __constant__ unsigned int b3_iv[8] = {
    0x6A09E667u,0xBB67AE85u,0x3C6EF372u,0xA54FF53Au,
    0x510E527Fu,0x9B05688Cu,0x1F83D9ABu,0x5BE0CD19u
};
__device__ __constant__ int b3_perm[16] = {2,6,3,10,7,0,4,13,1,11,12,5,9,14,15,8};
__device__ __forceinline__ unsigned int b3_rot(unsigned int x, int n) {
    return (x >> n) | (x << (32-n));
}
__device__ __forceinline__ void b3_g(unsigned int* v,int a,int b,int c,int d,unsigned int x,unsigned int y) {
    v[a]+=v[b]+x; v[d]=b3_rot(v[d]^v[a],16); v[c]+=v[d]; v[b]=b3_rot(v[b]^v[c],12);
    v[a]+=v[b]+y; v[d]=b3_rot(v[d]^v[a],8); v[c]+=v[d]; v[b]=b3_rot(v[b]^v[c],7);
}
__device__ __forceinline__ void b3_compress(const unsigned int* cv, const unsigned int* block,
        unsigned int counter_lo,unsigned int counter_hi,unsigned int len,unsigned int flags,unsigned int* out) {
    unsigned int v[16], m[16], next[16];
    #pragma unroll
    for(int i=0;i<8;++i) v[i]=cv[i];
    #pragma unroll
    for(int i=0;i<4;++i) v[8+i]=b3_iv[i];
    v[12]=counter_lo;v[13]=counter_hi;v[14]=len;v[15]=flags;
    #pragma unroll
    for(int i=0;i<16;++i)m[i]=block[i];
    #pragma unroll
    for(int round=0;round<7;++round) {
        b3_g(v,0,4,8,12,m[0],m[1]); b3_g(v,1,5,9,13,m[2],m[3]);
        b3_g(v,2,6,10,14,m[4],m[5]); b3_g(v,3,7,11,15,m[6],m[7]);
        b3_g(v,0,5,10,15,m[8],m[9]); b3_g(v,1,6,11,12,m[10],m[11]);
        b3_g(v,2,7,8,13,m[12],m[13]); b3_g(v,3,4,9,14,m[14],m[15]);
        #pragma unroll
        for(int i=0;i<16;++i)next[i]=m[b3_perm[i]];
        #pragma unroll
        for(int i=0;i<16;++i)m[i]=next[i];
    }
    #pragma unroll
    for(int i=0;i<8;++i)out[i]=v[i]^v[i+8];
}
extern "C" __global__ void make_seeds(const unsigned int* header,const unsigned long long* nonces,
        unsigned int* seeds,int count) {
    int n=blockIdx.x*blockDim.x+threadIdx.x;
    if(n>=count)return;
    unsigned int msg[16]={0},cv[8],out[8];
    #pragma unroll
    for(int i=0;i<8;++i){msg[i]=header[i];cv[i]=b3_iv[i];}
    msg[8]=(unsigned int)nonces[n];msg[9]=(unsigned int)(nonces[n]>>32);
    b3_compress(cv,msg,0,0,40,11,out);
    #pragma unroll
    for(int i=0;i<8;++i)seeds[n*8+i]=out[i];
}
extern "C" __global__ void expand_matrices(const unsigned int* seeds,signed char* a,signed char* b,int count) {
    int t=blockIdx.x*blockDim.x+threadIdx.x;
    if(t>=count*256)return;
    int n=t/256,counter=t%256;
    unsigned int msg[16]={0},cv[8],out[8];
    #pragma unroll
    for(int i=0;i<8;++i){msg[i]=seeds[n*8+i];cv[i]=b3_iv[i];}
    msg[8]=counter;
    b3_compress(cv,msg,0,0,36,11,out);
    unsigned int* target=(unsigned int*)(counter<128?a:b);
    int offset=n*1024+(counter%128)*8;
    #pragma unroll
    for(int i=0;i<8;++i)target[offset+i]=out[i];
}
extern "C" __global__ void expand_second(const unsigned int* seeds,signed char* d,int count) {
    int t=blockIdx.x*blockDim.x+threadIdx.x;
    if(t>=count*128)return;
    int n=t/128,counter=t%128;
    unsigned int msg[16]={0},cv[8],out[8];
    #pragma unroll
    for(int i=0;i<8;++i){msg[i]=seeds[n*8+i];cv[i]=b3_iv[i];}
    msg[8]=counter+1000;
    b3_compress(cv,msg,0,0,36,11,out);
    unsigned int* target=(unsigned int*)d;
    #pragma unroll
    for(int i=0;i<8;++i)target[n*1024+counter*8+i]=out[i];
}
extern "C" __global__ void hash_matrix(const unsigned int* seed,const int* matrix,unsigned int* result) {
    // BLAKE3(seed[32] || matrix[16384]): 16 full chunks plus a 32-byte chunk.
    int n=blockIdx.x,lane=threadIdx.x;
    __shared__ unsigned int tree[2][17][8];
    if(lane<17) {
        unsigned int cv[8],msg[16],out[8];
        #pragma unroll
        for(int i=0;i<8;++i)cv[i]=b3_iv[i];
        int blocks=lane==16?1:16;
        for(int block=0;block<blocks;++block) {
            #pragma unroll
            for(int i=0;i<16;++i) {
                int word=lane*256+block*16+i;
                if(word>=4104)msg[i]=0;
                else if(word<8)msg[i]=seed[n*8+word];
                else msg[i]=((const unsigned int*)matrix)[n*4096+word-8];
            }
            unsigned int flags=(block==0?1:0)|(block==blocks-1?2:0);
            b3_compress(cv,msg,lane,0,lane==16?32:64,flags,out);
            #pragma unroll
            for(int i=0;i<8;++i)cv[i]=out[i];
        }
        #pragma unroll
        for(int i=0;i<8;++i)tree[0][lane][i]=cv[i];
    }
    __syncthreads();
    int width=17,bank=0;
    while(width>1) {
        int pairs=width/2;
        if(lane<pairs) {
            unsigned int msg[16],cv[8],out[8];
            #pragma unroll
            for(int i=0;i<8;++i){msg[i]=tree[bank][lane*2][i];msg[i+8]=tree[bank][lane*2+1][i];cv[i]=b3_iv[i];}
            b3_compress(cv,msg,0,0,64,width==2?12:4,out);
            #pragma unroll
            for(int i=0;i<8;++i)tree[1-bank][lane][i]=out[i];
        }
        if((width&1)&&lane==pairs) {
            #pragma unroll
            for(int i=0;i<8;++i)tree[1-bank][pairs][i]=tree[bank][width-1][i];
        }
        __syncthreads();
        width=(width+1)/2;bank=1-bank;
    }
    if(lane<8)result[n*8+lane]=tree[bank][0][lane];
}
'''
