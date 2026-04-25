# NanoPay — User Flow (Updated for Gemini 3)

## Flow: The Agentic Commerce Loop

### 1. Coordinator Intelligence (Gemini 3 Pro)
- **Input:** User submits a complex research query.
- **Reasoning:** Gemini 3 Pro analyzes the query $\rightarrow$ Decomposes into 8-15 specialized sub-questions $\rightarrow$ Assigns each to a domain (Finance, Biotech, Legal, General).

### 2. The Transactional Handshake (x402)
- **Request:** Coordinator calls Expert Agent endpoint.
- **Challenge:** Expert Agent (Gemini 3 Flash) returns `HTTP 402` with `X-Price` and `X-Destination-Wallet`.
- **Execution:** Coordinator signs USDC authorization via Circle Wallet $\rightarrow$ Submits to Nanopayments API.
- **Verification:** Coordinator retries request with `X-Payment-Signature`. Expert Agent verifies via Circle Facilitator.

### 3. Value Settlement (Arc L1)
- **On-Chain:** The transaction settles on Arc.
- **Proof:** The `txHash` is returned to the Coordinator and emitted to the UI.
- **Result:** Expert Agent releases the domain-specific answer.
