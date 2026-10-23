# Tensorix TNX — experimental Tensor Core miner and validation audit

This branch is an auditable experimental network implementation. A new GPU backend executes both INT8 matrix rounds with NVIDIA Tensor Core MMA instructions and executes BLAKE3 on CUDA. The pre-existing `tensorix-v1.0.0-windows-cuda.zip` is a legacy unverified artifact and is not the source or the tested build for this branch. The distribution contains Python source and pinned dependencies, not a standalone EXE.

The original `start_miner.py` remains a CPU reference for compatibility and validation. Use `start_gpu_miner.py` for actual GPU mining. Its full PoW pipeline uses CUDA BLAKE3 stages and INT8 `mma.sync.aligned.m16n8k32.row.col.s32.s8.s8.s32` Tensor Core instructions. It fails when CUDA is unavailable; there is no CPU matrix or hash fallback. ASIC resistance, decentralized network operation and production security have not been demonstrated.

## What was checked

An isolated Windows run passed 42 regressions on 22 October 2026: real proof verification of the existing public genesis and historical block 2, a BLAKE3 vector, block identity/difficulty checks, account balance/nonce/transaction validation, transfer-fee routing, exact decimal wallet amounts, fail-closed disk loading, per-worker Stratum payout templates, duplicate rejection, concurrent block submission, rollback after a failed disk commit and HTTP API integration. Account and Stratum tests stub PoW where necessary; these are not GPU mining or internet production tests. A separate replay verified all 92 existing operator blocks with real PoW and preserved their original balances and nonces. See `AUDIT.md`.

## Fees: read before mining

Current release: one mining fee, enforced by the existing on-chain 98% / 2% subsidy split. The additional template-redirect scheduler was explicitly removed on 24 October 2026:

| Mechanism | Current code | Recipient |
| --- | --- | --- |
| Block reward split | 2% of subsidy for an external miner; a 10 TNX subsidy is split 9.8 / 0.2 | Founder address below |
| Additional miner dev fee | None: every template request uses the configured miner payout address | None |
| Transaction fee | Minimum 10 TNX per regular transaction, separate from mining fees | Same founder |

Public recipient: `tnx1b050bd6e525ac254ab212efce117cc636eb1166e`.

The 10 TNX transaction fee applies to signed wallet-to-wallet transfers. For example, sending 5 TNX with the default fee debits 15 TNX from the sender, credits 5 TNX to the recipient and credits the 10 TNX fee once to the founder when the block is accepted. Mining coinbase transactions have a transaction fee of zero; their separate 2% subsidy split is unchanged. The wallet parses amounts as exact decimal atomic units and rejects amounts with more than eight meaningful decimal places.

Historical block 2 predates these transfer-fee rules: it contains a 5 TNX transfer with a 0.0001 TNX fee included in its 10.0001 TNX coinbase. Only that exact block at height 2 with hash `000d11c2869efd16eff2d04e79f75bd6b807c4935b21e7b11c91baa9f7749de5` receives the original fee-to-coinbase accounting. Its PoW, hash binding, signatures, Merkle root, account balances and nonce are still checked. The old fee is not credited a second time. All other new blocks, wallet requests and mempool admission continue to require at least 10 TNX per regular transfer.

Older releases retained an additional legacy scheduler and could not be described as a single 2% mining fee. Upgrade to this release to remove that extra redirection. The separate 10 TNX wallet-transfer fee is unchanged.

The Stratum component is a solo relay: each worker's block template pays that worker and the founder. There is no tested shared PPLNS/PPS payout ledger for TNX in this branch.

## Local evaluation

Use an isolated Python environment and an empty working directory. Dependencies are pinned to the versions present in the test environment. BLAKE3 is mandatory; hashing never silently switches to SHA-256.

```sh
python -m venv .venv
# Activate the environment for your shell, then:
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

A new evaluation data directory can be initialized with the pinned existing genesis:

```sh
python -c "from tensorix.blockchain.chain import Blockchain; from tensorix.genesis import get_genesis_block; b=Blockchain('tensorix_data'); print(b.submit_block(get_genesis_block()))"
python start_node.py
```

Default listeners use loopback: node `127.0.0.1:8333`, optional relay `127.0.0.1:3333`. The legacy relay uses a Tensorix-specific notify payload and is not demonstrated to work with arbitrary Bitcoin Stratum V1 miners. No public TNX endpoint or two operating TNX Docker pools have been verified.

Never replace an existing chain with an empty data directory to work around a validation failure. The historical fee compatibility rule above allowed the complete existing 92-block ledger to load without rewriting it or changing its balances. Its original SHA-256 remained unchanged. These checks used temporary data copies; the live node has not been replaced by this review candidate.

## Remaining release decisions

1. Resolve the emission mismatch: the declared 21 million cap is not enforced. Current integer halving arithmetic emits 21,023,999.863344 TNX in total. This branch preserves that arithmetic.
2. Broaden GPU compatibility and performance testing beyond the two tested RTX 50-series cards; no speed or profitability guarantee is made.
3. Review the explicitly pinned historical fee compatibility rule and complete adversarial network testing before a public deployment.

No wallets, private keys, credential files or live chain state are included.

## Tensor Core GPU evaluation

The existing 64×64 INT8 / INT32 PoW contract is unchanged. Full PoW vectors match the CPU reference on RTX 5060 Ti and RTX 5060. The GPU path includes BLAKE3 seed generation, expansion, matrix output hashing and final proof hashing. The CPU reference remains the independent consensus verifier.

```sh
python -m pip install -r requirements-gpu.txt
python start_gpu_miner.py --address YOUR_COMPLETE_TNX_ADDRESS --device 0
# A second terminal for a second card:
python start_gpu_miner.py --address YOUR_COMPLETE_TNX_ADDRESS --device 1
```

A sufficiently recent NVIDIA driver and a CUDA-capable GPU with compute capability 8.0 or newer are required by this experimental build. Only RTX 5060 Ti and RTX 5060 are currently hardware-tested. The default URL is the public Docker node gateway. The operator PC must stay online.

The GPU and CPU-reference miners have no additional developer scheduler. Both always request work for the configured miner address. The existing on-chain 2% subsidy split and separate transfer-fee rules are unchanged.
