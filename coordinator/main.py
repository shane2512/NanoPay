import asyncio
import os
import time
from typing import Any, Dict, List, Set

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from coordinator.decomposer import CoordinatorIntelligence
from coordinator.payment import CirclePaymentClient

load_dotenv()


class ResearchQuery(BaseModel):
    query: str
    budget_cap: float = Field(default=0.50, ge=0.01)
    target_transactions: int = Field(default=12, ge=1, le=120)


class ConnectionManager:
    def __init__(self):
        self.connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.connections:
            self.connections.remove(websocket)

    async def broadcast(self, payload: Dict[str, Any]) -> None:
        stale: List[WebSocket] = []
        for socket in self.connections:
            try:
                await socket.send_json(payload)
            except RuntimeError:
                stale.append(socket)
        for socket in stale:
            self.disconnect(socket)


app = FastAPI(title="NeuroPay Coordinator")

_cors_raw = os.getenv("NEUROPAY_CORS_ALLOW_ORIGINS", "*")
_cors_origins = [item.strip() for item in _cors_raw.split(",") if item.strip()]
if not _cors_origins:
    _cors_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=os.getenv("NEUROPAY_CORS_ALLOW_CREDENTIALS", "false").lower() == "true",
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = ConnectionManager()
intel = CoordinatorIntelligence()
payment_client = CirclePaymentClient()

AGENT_MAP = {
    "FINANCE": "http://localhost:8001/query",
    "BIOTECH": "http://localhost:8001/query",
    "LEGAL": "http://localhost:8002/query",
    "GENERAL": "http://localhost:8002/query",
}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "coordinator",
        "models": {
            "decomposer": intel.decomposer_model,
            "report": intel.report_model,
        },
        "model_routing": intel.model_status(),
        "agents": AGENT_MAP,
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    await manager.broadcast({"type": "ws_connected", "at": time.time()})
    try:
        while True:
            msg = await websocket.receive_text()
            if msg.strip().lower() == "ping":
                await websocket.send_json({"type": "pong", "at": time.time()})
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.post("/api/research")
async def run_research(request: ResearchQuery):
    query = request.query.strip()
    if not query:
        return {"status": "error", "message": "query is required"}

    loop_delay = float(os.getenv("COORDINATOR_LOOP_DELAY_SECONDS", "0.2"))
    explorer_base = os.getenv(
        "ARC_EXPLORER_URL",
        "https://testnet.arcscan.app/address/0xcF1c22178A8F195860581ff18E17337253EDc340",
    )

    # 1) Decompose user query with Gemini Pro.
    sub_queries = intel.decompose_query(query, min_items=8, max_items=15)
    if request.target_transactions > len(sub_queries):
        sub_queries = intel.expand_sub_questions(query, sub_queries, request.target_transactions)
    else:
        sub_queries = sub_queries[: request.target_transactions]

    await manager.broadcast(
        {
            "type": "research_started",
            "query": query,
            "target_transactions": len(sub_queries),
            "budget_cap": request.budget_cap,
            "at": time.time(),
        }
    )

    results: List[Dict[str, Any]] = []
    total_spent = 0.0
    stopped_early = False

    # 2) Execute x402 payment loop and collect expert answers.
    for idx, sq in enumerate(sub_queries, start=1):
        domain = str(sq.get("domain", "GENERAL")).upper()
        question = str(sq.get("question", "")).strip()
        endpoint = AGENT_MAP.get(domain, AGENT_MAP["GENERAL"])

        if total_spent >= request.budget_cap:
            stopped_early = True
            await manager.broadcast(
                {
                    "type": "budget_exhausted",
                    "spent": total_spent,
                    "budget_cap": request.budget_cap,
                    "at": time.time(),
                }
            )
            break

        if not question:
            continue

        await manager.broadcast(
            {
                "type": "subquery_started",
                "index": idx,
                "total": len(sub_queries),
                "domain": domain,
                "question": question,
                "endpoint": endpoint,
                "at": time.time(),
            }
        )

        try:
            payment_result = payment_client.execute_x402_payment(endpoint, question)
            amount = float(payment_result.get("amount", 0))
            total_spent += amount

            tx_hash = payment_result.get("tx_hash")
            arc_url = _resolve_arc_explorer_url(explorer_base, tx_hash)
            detail = {
                "question": question,
                "domain": domain,
                "answer": payment_result.get("answer", ""),
                "tx_hash": tx_hash,
                "amount": amount,
                "agent_endpoint": endpoint,
                "arc_url": arc_url,
                "timestamp": time.time(),
            }
            results.append(detail)

            await manager.broadcast(
                {
                    "type": "payment_settled",
                    "index": idx,
                    "domain": domain,
                    "amount": amount,
                    "tx_hash": tx_hash,
                    "arc_url": arc_url,
                    "question": question,
                    "total_spent": round(total_spent, 6),
                    "at": detail["timestamp"],
                }
            )
            print("Settled {} query: {}".format(domain, tx_hash))
        except Exception as exc:
            print("Error processing {} query: {}".format(domain, exc))
            await manager.broadcast(
                {
                    "type": "payment_error",
                    "index": idx,
                    "domain": domain,
                    "question": question,
                    "error": str(exc),
                    "at": time.time(),
                }
            )

        await asyncio.sleep(loop_delay)

    # 3) Synthesize final report with Gemini Pro.
    final_report = intel.synthesize_report(query, results)
    margin = _build_margin_analysis(results)
    summary = {
        "total_spent": round(total_spent, 6),
        "transaction_count": len(results),
        "agents_used": sorted(list({item["domain"] for item in results})),
        "stopped_early": stopped_early,
        "target_transactions": len(sub_queries),
        "margin_analysis": margin,
    }

    await manager.broadcast(
        {
            "type": "report_ready",
            "summary": summary,
            "report": final_report,
            "at": time.time(),
        }
    )

    return {
        "status": "complete",
        "report": final_report,
        "summary": summary,
        "details": results,
    }


def _build_margin_analysis(details: List[Dict[str, Any]]) -> Dict[str, Any]:
    action_count = max(len(details), 1)
    total_spent = sum(float(item.get("amount", 0)) for item in details)
    per_action = total_spent / action_count if action_count else 0.0

    rails = [
        {"rail": "Stripe API", "per_action": 0.30, "base_fee": "$0.30 + 2.9%"},
        {"rail": "Ethereum Gas", "per_action": 0.50, "base_fee": "~$0.50"},
        {"rail": "PayPal", "per_action": 0.05, "base_fee": "$0.05 min"},
        {
            "rail": "Circle Nanopayments on Arc",
            "per_action": max(per_action, 0.000001),
            "base_fee": "$0.000001+",
        },
    ]

    for row in rails:
        row["cost_for_run"] = round(row["per_action"] * action_count, 4)

    viable_cost = rails[-1]["cost_for_run"]
    for row in rails:
        row["multiplier_vs_circle"] = (
            round(row["cost_for_run"] / viable_cost, 2) if viable_cost > 0 else None
        )

    return {
        "action_count": action_count,
        "total_spent_usdc": round(total_spent, 6),
        "avg_action_usdc": round(per_action, 6),
        "rows": rails,
    }


def _resolve_arc_explorer_url(base_url: str, tx_hash: str) -> str:
    """Supports either fixed address URLs or tx-hash templates for UI links."""
    url = (base_url or "").strip()
    if not url:
        return ""

    if "{tx_hash}" in url and tx_hash:
        return url.replace("{tx_hash}", tx_hash)

    normalized = url.rstrip("/")
    if tx_hash and normalized.lower().endswith("/tx"):
        return "{}/{}".format(normalized, tx_hash)

    return url


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("COORDINATOR_PORT", "8000")))
