# NeuroPay — Requirements Document (Updated for Gemini 3 & Arc)

> **Project:** NeuroPay — The Self-Monetizing AI Research Network  
> **Stack:** Gemini 3 (Pro/Flash), Circle Nanopayments, Arc L1, x402 Protocol

---

## 1. Project Overview
NeuroPay is a decentralized network where AI agents autonomously buy and sell specialized intelligence. 

**Intelligence Architecture:**
- **Coordinator Agent:** Powered by **Gemini 3 Pro**. Responsible for deep reasoning, complex task decomposition, and multi-agent orchestration.
- **Expert Agents:** Powered by **Gemini 3 Flash**. Optimized for low-latency, domain-specific responses and rapid payment verification.

---

## 2. Functional Requirements

### 2.1 The x402 Payment Loop (Core)
- **Handshake:** Expert Agents MUST return `HTTP 402` if no valid payment signature is present.
- **Verification:** All payments are verified via the **Circle x402 Facilitator** (No mocks).
- **Settlement:** All value transfers occur in USDC on **Arc L1**.

### 2.2 Gemini 3 Integration
- **Reasoning:** Use Gemini 3 Pro's "Deep Think" capabilities for query decomposition.
- **Function Calling:** Agents use Gemini's tool-use capabilities to interact with Circle APIs.
- **Multimodality:** The system is designed to eventually support multimodal inputs (images/PDFs) via Gemini 3.

### 2.3 Economic Constraints
- **Per-Action Pricing:** All sub-queries must cost $\le \$0.01$ USDC.
- **High Frequency:** The system must support $\ge 50$ transactions in a single demo run.
- **No Mocks:** Every "Payment Settled" event must correspond to a real transaction hash on the Arc Block Explorer.

---

## 3. Legacy Rails Failure Analysis
| Payment Rail | Min Fee | Cost for 100 sub-queries @ $0.002 each | Viable? |
|---|---|---|---|
| Stripe API | $0.30 + 2.9% | $30.00 | ❌ 150x Overpayment |
| Ethereum Gas | ~$0.50+ | $50.00+ | ❌ Unviable |
| PayPal | $0.05 min | $5.00 | ❌ 25x Overpayment |
| **Circle Nanopayments on Arc** | **$0.000001** | **$0.20** | ✅ **Only Viable Option** |
