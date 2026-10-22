# Tensorix validation and fee audit — 22 October 2026

## Scope and result

The legacy repository contained a ZIP only. This review branch adds an explicit source allowlist and reproducible tests. It does not replace the live operator installation, change its fee destinations, start a public node, or assert production readiness.

The reference candidate passed 24 offline regressions in 0.303 seconds on Windows with NumPy 2.5.4, BLAKE3 1.0.11, httpx 0.28.1 and cryptography 50.0.2. The exact final packaged source must be tested again if changed. A test return code of 0 was captured inside Python to avoid PowerShell treating unittest's normal stderr progress as failure or returning a null process exit code.

## Changes in the review candidate

| Prior behavior | Candidate behavior |
| --- | --- |
| BLAKE3 when installed, SHA-256 otherwise | BLAKE3 required; missing dependency fails closed |
| PoW checked without binding the claimed block hash | Claimed identity must match the computed Tensor-PoW hash and target |
| Miner could submit a different difficulty | Difficulty must equal the chain-derived retarget |
| Supplied transaction IDs trusted | IDs recomputed; duplicates rejected |
| Block account balances/nonces unchecked | Sequential signed transitions checked before state mutation |
| Negative or malformed coinbase could bypass checks | Coinbase amount, recipient, fee and height validated |
| Mempool accepted nonce gaps/repeated IDs | Contiguous sender sequence and duplicate rejection |
| Disk parse errors silently initialized a fresh chain | Full history validated; invalid source file retained |
| Fresh nodes could accept a different genesis | Existing public genesis hash pinned and genuinely verified |
| Same payout template broadcast to all Stratum workers | Each worker receives a job bound to its payout address |
| Shares counted before validation; missing jobs acknowledged | Authorization, job ownership, nonce, proof and duplicates checked before credit |
| Node-rejected block could still receive success | Relay credits and acknowledges a winning candidate only after node acceptance |
| CPU work presented as Tensor Core mining | CPU reference implementation labeled honestly |

The existing fee amounts/destinations and halving schedule are unchanged. Requiring valid historical blocks can reject an old ledger that previously passed permissive checks; no live migration has been performed.

## Fee reproduction in the original working source

The node accounting test produced 9.8 TNX miner / 0.2 TNX founder from a 10 TNX subsidy and rejected a block missing the required founder split. PoW was stubbed in this accounting test.

A separate miner test made 61 mocked template requests and 11,800 mocked hashes. A founder template was requested but its header was never hashed because polling the same block height discarded it. Three restarted sessions of 49 requests each produced no founder requests. Counting every 50th request therefore does not establish 2% of work or income. The legacy scheduler is left unchanged pending an explicit fee policy decision.

A separate 10 TNX minimum regular-transaction fee is credited entirely to the founder. Two functioning independent 2% mining mechanisms would combine to 3.96%, not 2%.

## Evidence and limits

The BLAKE3 empty-input vector and actual public genesis proof are tested without mocks. Public genesis hash: `0003692a2068dc16ed9092c63a22d35f74e8b0e213918a88d10f3e37bdba315b`, nonce 7092, timestamp 1792456684.

Other tests isolate account and transport policy with controlled hashes. They do not certify GPU performance, proof-of-work economics, payout profitability, chain safety, internet reachability or distributed consensus. The original whitepaper's GPU, supply, ASIC-resistance and production claims are unverified; this README and audit describe the tested implementation.

## Follow-up validation, 22 October 2026

The suite now contains 31 tests and passes on Windows Python 3.12 with the pinned dependencies. Seven added tests cover concurrent same-height submissions, rollback after failed durable replacement (including genesis), and HTTP API startup, real-genesis submission/reload, payout templates, invalid wire nonce and experimental status.

`Blockchain` serializes state updates and relevant reads using a reentrant lock. An exception during block persistence restores the prior chain, balances, account nonces and mempool. Wire bounds are checked before hashing an incoming block. The explorer no longer labels an experimental node as an online mainnet. The reference hash and relay descriptions no longer claim an implemented Tensor Core kernel or generic Stratum compatibility.

The operator's original ledger was copied for validation; the original SHA-256 stayed `701d6a27e1d3b527493748a66582999763de8bcfc8ad9dfa3204fec4f2db3c29`. Validation failed on a historical transaction with a fee below the current 10 TNX minimum. The original was not rewritten, replaced or restarted with an empty chain. Deployment over that ledger is blocked until historical fee rules and any migration are decided explicitly.

No mining fee, beneficiary, reward schedule, genesis, live data, GPU settings or node ports were changed by these checks. This is a source publication candidate for review, not a production or CUDA binary release.

## Wallet-transfer fee clarification and historical compatibility

The owner clarified that 10 TNX is the fee for wallet-to-wallet transfers. Mining reward transactions must not incur this 10 TNX transaction fee. The existing 2% mining subsidy split and legacy miner scheduler were left unchanged.

The original public ZIP establishes the older accounting: regular transactions allowed nonnegative fees, the default was 0.0001 TNX, and fees were included in the mining coinbase. Historical block 2 contains a signed transfer of 5 TNX with a 0.0001 TNX fee and a 10.0001 TNX coinbase. Lowering the minimum alone would still reject that old coinbase, and crediting its fee through both accounting paths would add it twice.

The review candidate pins the compatibility rule to height 2 and its exact BLAKE3/Tensor-PoW block hash `000d11c2869efd16eff2d04e79f75bd6b807c4935b21e7b11c91baa9f7749de5`. It verifies the real proof and claimed hash before using the original fee-to-coinbase rules for this block. Its transaction signatures, IDs, balances, nonces and Merkle root remain validated. Changing its claimed hash or nonce is rejected. Every other block and every new wallet/mempool request retains the 10 TNX minimum. The original history is not re-signed, re-mined, charged another fee or reset.

Wallet input conversion now preserves atomic units using decimal arithmetic. For instance, 0.00000003 TNX stays three atomic units. Invalid, nonfinite, negative and over-precision values, malformed recipient addresses and sub-minimum fees are rejected before loading wallet keys or contacting the node.

All 42 offline regressions passed on Windows. New accounting tests prove that a 5 TNX transfer with the default fee debits 15 TNX, pays 5 TNX to the recipient and credits 10 TNX to the founder once. Separate tests prove that coinbase transaction fees are zero, their existing 9.8/0.2 TNX split is retained, new low-fee transfers are rejected in mempool and blocks, and new coinbases cannot also collect the transfer fee. Accounting tests deliberately stub PoW; historical fixtures and the complete replay below do not.

A separate temporary-copy replay verified all 92 original blocks with real PoW, reaching height 91 and tip `00001ce7451638c19670b53a1530afa2f099e4d0ec8442ad5d2d1e959e1bf605`. All account balances and nonces exactly matched the original fee-to-coinbase accounting. Their sum remained 920 TNX. An in-process node/API startup over that copy reported height 91 and produced a height-92 template with 9.8/0.2 TNX subsidy outputs and zero coinbase transaction fees. Both original and temporary ledger bytes stayed unchanged; original SHA-256 remains `701d6a27e1d3b527493748a66582999763de8bcfc8ad9dfa3204fec4f2db3c29`.

This is an explicit historical consensus compatibility rule in the source review candidate. The live installation has not been replaced, and no real wallet transfer, mining session or public production deployment was performed by these tests.
