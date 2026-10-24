---
name: blockchain-web3
description: Explaining blockchain technology neutrally and technically - hash-linked blocks, Merkle trees, public-key signatures and wallets, consensus (proof of work, proof of stake), transactions and mempool, UTXO versus account model, smart contracts and gas, finality and forks, rollups, oracles, and decentralized application architecture. Use for how distributed ledgers work as systems; never for price, trading, returns or investment advice.
metadata:
  layer: domain
---

# Blockchain and Web3

## When to use

Topics about how a distributed ledger agrees on shared state without a central operator, how transactions are authorized and ordered, and what smart contracts do. Audience: developers and curious beginners. Treat it as a distributed-systems and cryptography topic. Speak neutrally: describe mechanisms, trade-offs and limits, and never advocate or disparage a network, token or project.

## Structure

1. The problem: many parties need one shared record and do not trust a single keeper.
2. The data structure: a transaction, a block holding many, each block containing the hash of the previous block header, so changing history changes every later hash.
3. Authorization: a private key signs, anyone verifies with the public key; show a transaction with a signature.
4. Agreement: who may add the next block and how nodes converge on one chain (the consensus rule). Explain one mechanism per video.
5. Execution (if smart contracts): deterministic code run by every node on the same inputs, paid in fees.
6. Limits: throughput, latency to finality, cost, privacy, and the oracle problem.

## Analogies and where they break

- Shared public ledger in a village square, copied by many keepers. Breaks: keepers follow a protocol rule to choose the valid copy; no one meets.
- Hash chain as sealed envelopes, each containing a fingerprint of the previous one. Breaks: nothing is secret, the chain is public; the seal gives tamper evidence, not secrecy.
- Digital signature as a wax seal only you can make but anyone can check. Breaks: it is tied to the exact message; it cannot be copied onto another one.
- Proof of work as a lottery where tickets cost computation. Breaks: difficulty adjusts, and the honest chain is the one with the most accumulated work.
- Smart contract as a vending machine. Breaks: its code is deployed publicly and cannot easily be changed once live, so bugs persist.
- Wallet as a keyring. Breaks: the assets are records on the ledger; the wallet holds the keys that authorize moving them.

## Misconceptions to preempt

- "Blockchain means Bitcoin." Bitcoin is one application of the idea.
- "Immutable means true." Data on chain is hard to alter, but it can be false when entered; the chain cannot verify off-chain facts.
- "Blockchains are anonymous." Addresses are pseudonymous and activity is public, so linking is often possible.
- "Smart contracts are legal contracts" or "smart". They are programs executing exactly as written.
- "Decentralized means no trust." Trust shifts to protocol rules, software, key holders and validator distribution.
- "A wallet stores coins."
- "Blockchain is just a slow database." It trades throughput for shared write access without a central operator; whether that trade fits depends on the need.
- "Transactions are instantly final." Finality is probabilistic or economic depending on the design.

## Terminology

Say node, validator or miner (match the mechanism), block, block header, hash, nonce, Merkle root, transaction, mempool, signature, public and private key, address, wallet, nonce (account transaction counter versus mining nonce: disambiguate), gas, fee, smart contract, deploy, call, state, UTXO, account model, consensus, fork, reorganization, finality, confirmation, layer 1, layer 2, rollup, oracle, bridge. Say "token" for contract-defined assets and "native currency" for the base asset. Avoid "to the moon", "HODL", "investment", "gains", "bull", "bear", "undervalued", and any price or return talk.

## Visual pairings

- data-structure-operations: chained blocks, a Merkle tree, tampering one block and watching hashes change.
- flow-diagram: life of a transaction from signing to confirmation.
- architecture-build-up: a dapp with frontend, wallet, node, contract, indexer.
- timeline-sequence: block production, finality, a fork resolving.
- comparison-split: proof of work versus proof of stake, UTXO versus accounts, layer 1 versus rollup.
- concept-metaphor: signatures, consensus.
- code-walkthrough: a very short contract function only when the scene needs it.

## Accuracy checks

- Hashes are one-way functions with fixed-size output; any input change gives an unrelated hash. Do not say hashing is encryption.
- Bitcoin: target block interval about ten minutes, difficulty retargets every 2,016 blocks, supply capped at 21 million.
- Ethereum moved from proof of work to proof of stake in September 2022; slots are 12 seconds. State the date when describing it as current, because protocols upgrade.
- Block size, fees, throughput and validator counts change; give a figure only with its date and network.
- Signing uses the private key; verification uses the public key. Never invert this.
- Gas measures computation, and the fee depends on gas used and the market price per unit.
- Do not describe a real exploit's amounts or victims; name classes such as reentrancy conceptually and the defense (checks-effects-interactions, audits, formal verification).

## Do

- Present trade-offs for each design choice.
- Use made-up names and short fake hashes in examples.
- Say what a mechanism guarantees and what it does not.

## Don't

- Don't give price, trading, returns, or "should you buy" content.
- Don't call any project the best or a scam.
- Don't display real private keys, seed phrases or addresses of real people.
