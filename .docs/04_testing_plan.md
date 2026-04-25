# NanoPay — Final Testing Plan (Claude Code)

> **Purpose:** Step-by-step test suite for Claude Code to execute before submission  
> **Run order:** Unit → Integration → E2E → Demo Validation → Submission Checklist  
> **Environment:** Arc testnet, Circle testnet APIs, localhost

---

## Pre-Test Setup

Before running any tests, verify the environment:

```bash
# 1. Confirm all environment variables are set
echo $CIRCLE_API_KEY
echo $COORDINATOR_WALLET_ID
echo $FINANCE_AGENT_WALLET_ID
echo $BIOTECH_AGENT_WALLET_ID
echo $LEGAL_AGENT_WALLET_ID
echo $GENERAL_AGENT_WALLET_ID
echo $CIRCLE_FACILITATOR_URL

# 2. Confirm all agent servers are running
curl -s http://localhost:8001/health  # Finance Agent
curl -s http://localhost:8002/health  # Biotech Agent
curl -s http://localhost:8003/health  # Legal Agent
curl -s http://localhost:8004/health  # General Agent

# 3. Confirm coordinator is running
curl -s http://localhost:8000/health

# 4. Confirm coordinator wallet has sufficient USDC balance
# Expected: >= 1.00 USDC testnet balance
```

---

## Section 1: Unit Tests

### Test 1.1 — Query Decomposer

```python
# tests/test_decomposer.py

def test_decompose_returns_list():
    result = decompose_query("Analyze GLP-1 drug patents in Asia")
    assert isinstance(result, list)
    assert len(result) >= 5
    assert len(result) <= 15

def test_decompose_assigns_valid_domains():
    result = decompose_query("Analyze GLP-1 drug patents in Asia")
    valid_domains = {"FINANCE", "BIOTECH", "LEGAL", "GENERAL"}
    for sq in result:
        assert sq["domain"] in valid_domains

def test_decompose_all_questions_are_strings():
    result = decompose_query("AI regulation in G20 countries")
    for sq in result:
        assert isinstance(sq["question"], str)
        assert len(sq["question"]) > 10

def test_decompose_mixed_domain_query():
    # A query touching all domains should produce all domain types
    result = decompose_query(
        "Comprehensive analysis of AI regulation: legal frameworks, "
        "financial implications, biotech applications"
    )
    domains_found = {sq["domain"] for sq in result}
    assert len(domains_found) >= 2  # At minimum 2 different domains
```

**Expected:** All 4 tests pass. Decomposer returns 5–15 sub-questions with valid domains.

---

### Test 1.2 — Domain Router

```python
# tests/test_router.py

def test_routes_finance_to_correct_endpoint():
    endpoint = route({"domain": "FINANCE"})
    assert endpoint == "http://localhost:8001"

def test_routes_biotech_to_correct_endpoint():
    endpoint = route({"domain": "BIOTECH"})
    assert endpoint == "http://localhost:8002"

def test_routes_legal_to_correct_endpoint():
    endpoint = route({"domain": "LEGAL"})
    assert endpoint == "http://localhost:8003"

def test_routes_unknown_to_general():
    endpoint = route({"domain": "UNKNOWN_DOMAIN"})
    assert endpoint == "http://localhost:8004"

def test_routes_general_to_correct_endpoint():
    endpoint = route({"domain": "GENERAL"})
    assert endpoint == "http://localhost:8004"
```

**Expected:** All 5 tests pass.

---

### Test 1.3 — Expert Agent 402 Response

```bash
# Run for each agent (ports 8001–8004)

# Test: No payment header → must return 402
curl -v "http://localhost:8001/query?q=What+are+revenue+trends+for+GLP-1+drugs"

# Expected response:
# HTTP/1.1 402 Payment Required
# X-Price: 0.003
# X-Destination-Wallet: arc:0x<FINANCE_WALLET_ADDRESS>
# X-Chain: arc-testnet
# X-Payment-Standard: x402-nanopayments
# Content-Type: application/json
# {"error": "Payment required", "price": 0.003, "currency": "USDC"}
```

**Validate:**
- [ ] Status code is exactly 402
- [ ] `X-Price` header is present and is a float ≤ 0.01
- [ ] `X-Destination-Wallet` header is present and starts with `arc:0x`
- [ ] `X-Chain` is `arc-testnet`
- [ ] `X-Payment-Standard` is `x402-nanopayments`

---

### Test 1.4 — Expert Agent Answer Quality

```python
# tests/test_agents.py
# These tests bypass payment (use internal method directly) to check LLM quality

def test_finance_agent_answers_finance_question():
    agent = FinanceAgent()
    answer = agent.generate_answer("What are the revenue trends for GLP-1 drugs in Asia?")
    assert len(answer) > 50
    assert any(word in answer.lower() for word in ["revenue", "market", "billion", "growth"])

def test_biotech_agent_answers_science_question():
    agent = BiotechAgent()
    answer = agent.generate_answer("What patents cover semaglutide formulations filed in China?")
    assert len(answer) > 50
    assert any(word in answer.lower() for word in ["patent", "compound", "formulation", "drug"])

def test_legal_agent_answers_regulatory_question():
    agent = LegalAgent()
    answer = agent.generate_answer("What is the regulatory approval pathway for GLP-1 drugs in Japan?")
    assert len(answer) > 50
    assert any(word in answer.lower() for word in ["regulatory", "approval", "agency", "compliance"])
```

**Expected:** All 3 tests pass with substantive answers (>50 chars, domain-relevant vocabulary).

---

## Section 2: Integration Tests

### Test 2.1 — Full x402 Payment Handshake (Single Transaction)

```python
# tests/test_payment_integration.py

def test_single_x402_payment_flow():
    """
    End-to-end: request → 402 → sign → nanopayments → retry → 200 + answer
    """
    result = execute_x402_payment(
        endpoint="http://localhost:8001",
        sub_question={"text": "What are the revenue projections for GLP-1 drugs in South Korea?", "domain": "FINANCE"},
        budget_remaining=0.50
    )
    
    # Payment succeeded
    assert result["tx_hash"] is not None
    assert len(result["tx_hash"]) > 10
    
    # Answer was returned
    assert result["answer"] is not None
    assert len(result["answer"]) > 20
    
    # Amount is within expected range
    assert 0.001 <= result["amount"] <= 0.01

def test_payment_reduces_balance():
    """
    Coordinator wallet balance should decrease after payment
    """
    balance_before = get_wallet_balance(COORDINATOR_WALLET_ID)
    
    execute_x402_payment(
        endpoint="http://localhost:8001",
        sub_question={"text": "test question", "domain": "FINANCE"},
        budget_remaining=0.50
    )
    
    balance_after = get_wallet_balance(COORDINATOR_WALLET_ID)
    assert balance_after < balance_before

def test_agent_wallet_receives_payment():
    """
    Finance Agent wallet balance should increase after payment
    """
    balance_before = get_wallet_balance(FINANCE_AGENT_WALLET_ID)
    
    execute_x402_payment(
        endpoint="http://localhost:8001",
        sub_question={"text": "test question", "domain": "FINANCE"},
        budget_remaining=0.50
    )
    
    # Note: Nanopayments settles periodically — check ledger balance, not on-chain
    ledger_balance = get_nanopayments_ledger_balance(FINANCE_AGENT_WALLET_ID)
    assert ledger_balance > balance_before
```

**Expected:** All 3 tests pass. One transaction appears in Circle Developer Console.

---

### Test 2.2 — Budget Cap Enforcement

```python
def test_budget_cap_stops_execution():
    """
    If budget_remaining < agent price, BudgetExceededError must be raised
    """
    import pytest
    with pytest.raises(BudgetExceededError):
        execute_x402_payment(
            endpoint="http://localhost:8001",  # Finance agent costs $0.003
            sub_question={"text": "test", "domain": "FINANCE"},
            budget_remaining=0.001  # Less than agent price → must raise
        )

def test_coordinator_stops_at_cap():
    """
    Full coordinator run with tight budget — should stop early
    """
    results = run_research_sync(
        query="Comprehensive analysis of AI regulation in G20 countries",
        budget_cap=0.01  # Very tight — should only complete ~3 sub-questions
    )
    
    assert results["spent"] <= 0.01
    assert results["stopped_early"] == True
    assert len(results["transactions"]) < 12
```

**Expected:** Both tests pass. System respects budget without crashing.

---

### Test 2.3 — Agent Fallback (Unavailable Agent)

```python
def test_falls_back_to_general_on_503():
    """
    If primary domain agent is down, coordinator should fallback to General Agent
    """
    # Temporarily shut down Finance Agent
    # (In test environment, mock the endpoint to return 503)
    with mock_agent_unavailable("http://localhost:8001"):
        result = execute_x402_payment(
            endpoint="http://localhost:8001",
            sub_question={"text": "What are market cap trends?", "domain": "FINANCE"},
            budget_remaining=0.50,
            fallback_endpoint="http://localhost:8004"
        )
    
    assert result is not None
    assert result["answer"] is not None
    # Verify it used General Agent (port 8004)
    assert result["agent_used"] == "GENERAL"
```

---

### Test 2.4 — Arc Block Explorer Link Validity

```python
def test_tx_hash_resolves_on_arc_explorer():
    """
    Every tx_hash must produce a valid Arc Block Explorer URL
    """
    result = execute_x402_payment(
        endpoint="http://localhost:8001",
        sub_question={"text": "test", "domain": "FINANCE"},
        budget_remaining=0.50
    )
    
    arc_url = f"https://explorer.arc.testnet/tx/{result['tx_hash']}"
    response = requests.get(arc_url)
    
    # Explorer returns 200 for valid transactions
    assert response.status_code == 200
```

**Expected:** Test passes. Arc Block Explorer returns 200 for the transaction URL.

---

## Section 3: End-to-End Tests

### Test 3.1 — Full Research Query (API Level)

```bash
# POST a full research query to the coordinator API
curl -X POST http://localhost:8000/api/research \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Analyze GLP-1 drug patent landscape in Asia",
    "budget_cap": 0.50
  }'

# Expected response (may take 20-30 seconds):
{
  "status": "complete",
  "report": "## GLP-1 Patent Landscape: Asia\n\n...",
  "summary": {
    "total_spent_usdc": 0.036,
    "transaction_count": 12,
    "agents_used": ["FINANCE", "BIOTECH", "LEGAL"],
    "transactions": [
      {
        "agent": "FINANCE",
        "amount": 0.003,
        "tx_hash": "0xABC...",
        "arc_url": "https://explorer.arc.testnet/tx/0xABC..."
      }
      // ... 11 more
    ]
  }
}
```

**Validate:**
- [ ] `status` is `"complete"`
- [ ] `report` length > 500 characters
- [ ] `transaction_count` >= 8
- [ ] All `tx_hash` values are non-empty strings
- [ ] All `arc_url` values follow the correct format
- [ ] `total_spent_usdc` ≤ `budget_cap`

---

### Test 3.2 — WebSocket Live Events

```javascript
// tests/test_websocket.js (run with Node.js)

const WebSocket = require('ws');

const ws = new WebSocket('ws://localhost:8000/ws');
const events = [];

ws.on('message', (data) => {
    events.push(JSON.parse(data));
});

// Trigger a research query
fetch('http://localhost:8000/api/research', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
        query: "Analyze GLP-1 drug patent landscape in Asia",
        budget_cap: 0.50
    })
});

// Wait 35 seconds then assert
setTimeout(() => {
    const paymentEvents = events.filter(e => e.type === 'payment_settled');
    const reportEvent = events.find(e => e.type === 'report_ready');
    
    console.assert(paymentEvents.length >= 8, 'Expected 8+ payment events');
    console.assert(reportEvent !== undefined, 'Expected report_ready event');
    console.assert(reportEvent.report.length > 200, 'Expected substantial report');
    
    paymentEvents.forEach(e => {
        console.assert(e.agent !== undefined, 'Event missing agent field');
        console.assert(e.amount > 0, 'Event missing amount');
        console.assert(e.tx_hash !== undefined, 'Event missing tx_hash');
        console.assert(e.arc_url.includes('explorer.arc.testnet'), 'Invalid arc_url');
    });
    
    console.log(`✅ WebSocket test passed: ${paymentEvents.length} payment events received`);
    ws.close();
}, 35000);
```

**Expected:** 8+ `payment_settled` events, 1 `report_ready` event, all fields present.

---

### Test 3.3 — Browser UI Smoke Test

Open `http://localhost:3000` and manually verify:

- [ ] Query input field accepts text
- [ ] Budget slider works (drag min/max)
- [ ] "Run Research" button triggers loading state
- [ ] Transaction feed appears and rows populate in real time
- [ ] Progress bar increments with each transaction
- [ ] Running total USDC counter updates
- [ ] At least one "→ Arc" link is clickable and opens Arc Block Explorer
- [ ] Final report renders as formatted text
- [ ] Cost summary shows correct totals
- [ ] "Legacy cost comparison" callout is visible
- [ ] No JavaScript errors in browser console

---

## Section 4: Demo Validation (Hackathon Submission Requirements)

### Test 4.1 — 50+ Transaction Demo

```bash
# Run the high-transaction demo query
curl -X POST http://localhost:8000/api/research \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Comprehensive analysis of AI regulation across G20 nations: legal frameworks, financial market implications, biotech and pharma regulatory impacts, patent filing trends, and compliance requirements for AI-driven medical devices",
    "budget_cap": 1.00
  }'
```

**Must validate:**
- [ ] `transaction_count` >= 50
- [ ] All 4 agent domains used (FINANCE, BIOTECH, LEGAL, GENERAL)
- [ ] Total cost ≤ $0.50 USDC (well under $1.00 cap)
- [ ] All tx hashes non-empty and unique
- [ ] No duplicate payments (same tx_hash appears only once)

---

### Test 4.2 — Per-Action Price ≤ $0.01 Check

```python
def test_all_payments_under_one_cent():
    results = run_research_sync(
        query="Comprehensive AI regulation analysis across G20",
        budget_cap=1.00
    )
    for tx in results["transactions"]:
        assert tx["amount"] <= 0.01, f"Transaction {tx['tx_hash']} exceeded $0.01: {tx['amount']}"
```

**Expected:** All transactions ≤ $0.01. This is a hard hackathon requirement.

---

### Test 4.3 — Arc Block Explorer Proof

```python
def test_arc_explorer_proof():
    """
    At least one transaction must be verifiable on Arc Block Explorer.
    Capture the URL for submission screenshot.
    """
    results = run_research_sync(
        query="Analyze GLP-1 drug patent landscape in Asia",
        budget_cap=0.50
    )
    
    first_tx = results["transactions"][0]
    arc_url = first_tx["arc_url"]
    
    print(f"\n✅ SUBMISSION PROOF URL:\n{arc_url}\n")
    print("Screenshot this URL for your hackathon submission.")
    
    response = requests.get(arc_url)
    assert response.status_code == 200
```

---

### Test 4.4 — Circle Developer Console Verification

**Manual step — do this before submission:**

1. Log into [console.circle.com](https://console.circle.com)
2. Navigate to Transactions → Nanopayments
3. Confirm you can see 50+ transactions from the demo run
4. Screenshot the transaction list
5. Click one transaction to show detail: From, To, Amount, Status: Confirmed

---

### Test 4.5 — Margin Explanation Validation

Verify the README or submission includes this table (must be present in submission):

```markdown
| Payment Rail | Min Fee | Cost for 50 sub-queries @ $0.003 | Viable? |
|---|---|---|---|
| Stripe API | $0.30 + 2.9% | $15.00 | ❌ 100× overpayment |
| Ethereum gas | ~$1.00 avg | $50.00 | ❌ Completely unviable |
| PayPal | $0.05 min | $2.50 | ❌ 17× overpayment |
| Circle Nanopayments on Arc | $0.000001 | $0.15 | ✅ Only viable option |
```

- [ ] Table present in README.md
- [ ] Numbers are accurate
- [ ] At least 3 legacy options compared

---

## Section 5: Submission Checklist

Run through this checklist in order before submitting:

### Code & Repository
- [ ] All code pushed to GitHub (public repository)
- [ ] MIT License file present at root
- [ ] README.md contains: project description, setup instructions, which Circle products used, margin explanation table
- [ ] `.env.example` present (no real API keys in repo)
- [ ] `requirements.txt` or `package.json` complete — `pip install -r requirements.txt` works cleanly

### Functional Verification
- [ ] Full query runs end-to-end in < 45 seconds
- [ ] 50+ transactions achieved in demo query
- [ ] All transactions ≤ $0.01 each
- [ ] Budget cap enforcement tested and working
- [ ] WebSocket live feed working in browser
- [ ] Final report rendered correctly

### Submission Artifacts
- [ ] Demo video recorded (3 minutes max):
  - [ ] Show query input
  - [ ] Show live transaction feed (clearly see payments settling)
  - [ ] Show Arc Block Explorer for at least one transaction
  - [ ] Show final report
  - [ ] Show cost summary with legacy comparison
- [ ] Arc Block Explorer screenshot saved (shows confirmed transaction, $0.00 gas)
- [ ] Circle Developer Console screenshot saved (shows 50+ Nanopayments transactions)

### LabLab.ai Submission Form
- [ ] Project title: "NanoPay"
- [ ] Track selected: Agentic Payment Loop (+ X402 Commerce)
- [ ] Circle products used field completed:
  ```
  Circle Nanopayments API (primary settlement rail), 
  Circle Developer Wallets (5 wallets: 1 coordinator + 4 expert agents),
  x402 Facilitator (payment verification),
  Arc L1 testnet (on-chain settlement)
  ```
- [ ] **Circle Product Feedback field completed** (required for $500 USDC bonus):
  - Which products used and why
  - What worked well
  - Developer friction points encountered
  - Suggestions for improvement
- [ ] GitHub repo URL added
- [ ] Demo video URL added
- [ ] Arc Block Explorer transaction URL added

---

## Quick Test Run Commands (Claude Code)

```bash
# Run all unit tests
pytest tests/test_decomposer.py tests/test_router.py tests/test_agents.py -v

# Run integration tests
pytest tests/test_payment_integration.py -v

# Run E2E API test
curl -X POST http://localhost:8000/api/research \
  -H "Content-Type: application/json" \
  -d '{"query": "Analyze GLP-1 drug patent landscape in Asia", "budget_cap": 0.50}' \
  | python -m json.tool

# Run 50+ transaction demo
curl -X POST http://localhost:8000/api/research \
  -H "Content-Type: application/json" \
  -d '{"query": "Comprehensive analysis of AI regulation across G20 nations: legal frameworks, financial implications, biotech impacts, patent trends, and compliance requirements", "budget_cap": 1.00}' \
  | python -m json.tool

# Run submission checklist validation
pytest tests/test_submission_requirements.py -v --tb=short
```

---

## Pass/Fail Summary Table

| Test Suite | Tests | Must Pass Before |
|---|---|---|
| Unit Tests | 12 | Starting Phase 2 |
| Integration Tests | 7 | Starting Phase 3 |
| E2E API Tests | 2 | Starting Phase 4 |
| Browser Smoke Test | 10 items | Phase 4 polish |
| Demo Validation | 5 | Recording demo video |
| Submission Checklist | 20 items | Hitting submit |
