# Tensorix TNX — experimental reference and validation audit

This branch is an auditable Python prototype, not a production coin launch or a verified CUDA miner release. The pre-existing `tensorix-v1.0.0-windows-cuda.zip` is a legacy unverified artifact and is not the source or the tested build for this branch. No new executable release is provided.

The mining loop executes the NumPy CPU reference hash. Installing CuPy does not turn it into a Tensor Core miner. CUDA/Tensor Core acceleration, ASIC resistance, decentralized network operation and production security have not been demonstrated.

## What was checked

An isolated Windows run passed 31 regressions on 22 October 2026: real proof verification of the existing public genesis and a BLAKE3 vector, block identity/difficulty checks, account balance/nonce/transaction validation, fail-closed disk loading, per-worker Stratum payout templates, duplicate rejection, concurrent block submission, rollback after a failed disk commit and HTTP API integration. Account and Stratum tests stub PoW where necessary; these are not GPU mining or internet production tests. See `AUDIT.md`.

## Fees: read before mining

The fee mechanisms are preserved for review; no fee policy was silently changed:

| Mechanism | Current code | Recipient |
| --- | --- | --- |
| Block reward split | 2% of subsidy for an external miner; a 10 TNX subsidy is split 9.8 / 0.2 | Founder address below |
| Legacy miner dev scheduler | Every 50th template request redirects to the founder; isolated tests show this does not guarantee 2% of mining work | Same founder |
| Transaction fee | Minimum 10 TNX per regular transaction, separate from mining fees | Same founder |

Public recipient: `tnx1b050bd6e525ac254ab212efce117cc636eb1166e`.

If both separate mining fee mechanisms operated reliably, their combined expected deduction would be 3.96%. This code must not be advertised as a guaranteed single 2% total fee until the intended policy is selected and tested.

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

Never replace an existing chain with an empty data directory to work around a validation failure. A read-only check of a copy of the operator's legacy ledger failed because it contains a transaction below the enforced 10 TNX minimum fee. The original ledger's SHA-256 remained unchanged. This source must not replace that live node until historical validation and migration policy have been resolved explicitly.

## Remaining release decisions

1. Select a single 2% mining fee or explicitly disclose and implement separate mining fees; the legacy scheduler remains unreliable.
2. Resolve the emission mismatch: the declared 21 million cap is not enforced. Current integer halving arithmetic emits 21,023,999.863344 TNX in total. This branch preserves that arithmetic.
3. Implement and verify a real GPU kernel before making CUDA/Tensor Core performance claims.
4. Complete a ledger compatibility/migration review, node/API integration and adversarial network testing before a public deployment.

No wallets, private keys, credential files or live chain state are included.
