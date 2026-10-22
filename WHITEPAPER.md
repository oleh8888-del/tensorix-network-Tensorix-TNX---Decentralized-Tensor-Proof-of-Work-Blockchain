# Tensorix (TNX): experimental protocol notes

This describes the inspected Python reference implementation as of 22 October 2026. It is not a production launch announcement. No CUDA/Tensor Core implementation, ASIC-resistance result, decentralized peer synchronization or public mining endpoint has been demonstrated.

The reference hash derives a seed from BLAKE3(header digest || little-endian uint64 nonce). Repeated BLAKE3 expansion creates two 64 × 64 INT8 matrices. NumPy multiplies their INT32 conversions on the CPU. A BLAKE3 digest of the seed and little-endian INT32 result seeds another INT8 matrix. The second multiplication uses the first result modulo 127, converted through INT8 to INT32. BLAKE3 of the intermediate digest and final little-endian INT32 matrix is compared with the network target. There is no SHA-256 fallback.

The header digest commits to the uint32 height, previous block hash, transaction Merkle root, uint64 timestamp and little-endian float64 difficulty. Existing byte encoding and the existing public genesis are preserved. The pinned genesis hash is `0003692a2068dc16ed9092c63a22d35f74e8b0e213918a88d10f3e37bdba315b`.

| Parameter | Inspected implementation |
| --- | --- |
| Ticker | TNX |
| Initial subsidy | 10 TNX |
| Target block interval | 60 seconds |
| Halving interval | 1,051,200 blocks |
| Difficulty adjustment | LWMA, 30-block window |
| On-chain founder subsidy share | At least 2% when an external miner receives subsidy |
| Minimum regular transaction fee | 10 TNX, credited to the founder |
| Miner dev scheduler | Redirects every 50th template fetch; does not establish 2% of actual mining work |
| Nominal cap | 21 million TNX is declared but not enforced by the reward arithmetic |
| Actual arithmetic total | 21,023,999.863344 TNX |

The solo Stratum relay issues separate payout templates for each authorized worker. It verifies submitted nonces, rejects duplicates and waits for the node's acceptance before acknowledging a block. Its notify payload is specific to Tensorix. Shared PPLNS/PPS payouts and generic Bitcoin Stratum V1 miner compatibility are not implemented or established.

A 10 TNX external-miner subsidy is split into 9.8 TNX for the miner and 0.2 TNX for the founder. A second reliable 2% miner fee would produce a combined expected deduction of 3.96%; the current legacy scheduler does not reliably implement that second charge. The intended single-versus-separate mining fee policy needs an explicit decision. This audit does not change it.

Block validation checks the pinned genesis, computed hash, proof, expected difficulty, Merkle root, transaction IDs, signatures, balances and account nonces. State mutations are serialized within one process. A failed file commit restores the in-memory chain and account state. The 31-test Windows suite includes real-genesis verification and isolated HTTP, concurrency and persistence regressions, with mocked PoW in accounting and relay tests.

A copy of the existing operator ledger fails strict validation because of a transaction below the current minimum fee. Its original file was preserved byte for byte. Historical fee validation, migration policy, network security and real accelerated mining remain release blockers. No public value, production readiness or mining performance is asserted.
