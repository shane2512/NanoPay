# NanoPay

NanoPay is a multi-agent research network where a coordinator breaks down complex questions, pays specialist agents via Circle Nanopayments using USDC on Arc testnet, and returns a synthesized report with transaction proof.

## 1. Prerequisites

- Node.js 18+
- Python 3.10+ (3.11 recommended)
- Git
- Circle Developer account (testnet API key + faucet access)
- Google AI Studio key for Gemini

## 2. Clone and Install

### Windows (PowerShell)

cd path\to\workspace
git clone <your-repo-url>
cd Lablab

python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

npm install

### macOS/Linux

cd /path/to/workspace
git clone <your-repo-url>
cd Lablab

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

npm install

## 3. Configure Environment

1. Copy environment template:
- Windows PowerShell: Copy-Item .env.example .env
- macOS/Linux: cp .env.example .env

2. Open .env and set required values:
- GEMINI_API_KEY
- CIRCLE_API_KEY
- CIRCLE_ENTITY_SECRET (if already created in Circle)
- Wallet IDs and addresses (if manually provisioning)
- Optional tuning values for Gemini, CORS, and coordinator loop timing

3. Keep all values on testnet for this project.

## 4. Provision Wallets (Recommended)

Run the setup script to create wallet set and wallets on ARC-TESTNET:

node --env-file=.env scripts/setup-neuropay-wallets.mjs

What this script does:
- Registers or uses Circle entity secret flow
- Creates a wallet set
- Creates 3 wallets (Coordinator, Specialist A, Specialist B)
- Writes wallet IDs/addresses back into .env
- Prompts you to fund coordinator wallet via Circle faucet
- Sends 1 USDC test transfers to specialists for flow verification
- Writes wallet artifact JSON into output folder

## 5. Register Agent Identities on ERC-8004

node --env-file=.env scripts/register-neuropay-agents.mjs

This writes registration artifacts to output/erc8004-registrations.json.

## 6. Start Backend Services (3 Terminals)

### Terminal 1: Specialist A

python agents/specialist_a.py

### Terminal 2: Specialist B

python agents/specialist_b.py

### Terminal 3: Coordinator

python coordinator/main.py

Default ports:
- Coordinator: 8000
- Specialist A: 8001
- Specialist B: 8002

## 7. Start Frontend

Use an HTTP server (recommended), not file://

cd frontend
python -m http.server 8080

Open:
http://localhost:8080

The frontend calls coordinator at localhost:8000 by default.

## 8. Verify Health

Open these URLs or use curl:
- http://localhost:8000/health
- http://localhost:8001/health
- http://localhost:8002/health

## 9. Run a Demo Query

Use the UI or call API directly:

POST http://localhost:8000/api/research

Sample JSON body:
{
  "query": "Comprehensive analysis of AI regulation across G20 nations",
  "budget_cap": 0.5,
  "target_transactions": 12
}

Expected behavior:
- Coordinator decomposes query
- Specialist endpoints first respond with HTTP 402 unless paid
- Coordinator settles payments and retries with payment proof
- Final synthesized report and transaction details are returned
- Arc proof links appear in response/dashboard

## 10. Stress Tests and Proof Artifacts

Run economic proof stress test:
python tests/stress_test_economic_proof.py

This generates artifacts in output, including:
- output/stress-test-tx-hashes.txt
- summary logs with transaction counts, spend, and sample Arc explorer proof

Optional concurrent load script:
python scripts/stress_test_50txn.py

## 11. Troubleshooting

- If setup script fails with entity secret already set:
  Use existing CIRCLE_ENTITY_SECRET or create a new Circle API key.
- If WebSocket feed is not live:
  Confirm websockets package is installed from requirements.txt.
- If browser shows CORS errors:
  Serve frontend via HTTP and keep NANOPAY_CORS_ALLOW_ORIGINS configured.
- If API call fails after payment:
  Check Circle gateway/facilitator URL and wallet funding.
- If specialists fail at startup:
  Verify SPECIALIST_A_WALLET_ID and SPECIALIST_B_WALLET_ID are present in .env.

## 12. Project Structure (High Level)

- coordinator: orchestration, payment loop, synthesis
- agents: x402-gated specialist services
- scripts: Circle wallet setup, transfers, and registration utilities
- frontend: live dashboard
- tests: stress and economic proof flows
- output: generated proof artifacts