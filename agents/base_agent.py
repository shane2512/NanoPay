"""Core x402-gated Expert Agent implementation."""

import json
import os
import time
from typing import Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Header, Response

from coordinator.gemini_rest import GeminiRestClient

load_dotenv()


class AgentConfig:
    CIRCLE_API_KEY = os.getenv("CIRCLE_API_KEY")
    FACILITATOR_URL = os.getenv("CIRCLE_GATEWAY_API_URL") or os.getenv("CIRCLE_FACILITATOR_URL")
    COORDINATOR_WALLET_ADDRESS = (os.getenv("COORDINATOR_WALLET_ADDRESS") or "").lower()
    ARC_RPC_URL = os.getenv("ARC_RPC_URL", "https://rpc.testnet.arc.network/")
    ARC_USDC_TOKEN_ADDRESS = os.getenv(
        "ARC_USDC_TOKEN_ADDRESS",
        "0x3600000000000000000000000000000000000000",
    ).lower()
    ARC_RECEIPT_MAX_WAIT_SECONDS = float(os.getenv("ARC_RECEIPT_MAX_WAIT_SECONDS", "35"))
    ARC_RECEIPT_POLL_SECONDS = float(os.getenv("ARC_RECEIPT_POLL_SECONDS", "2"))
    GEMINI_EXPERT_MODEL = os.getenv("GEMINI_EXPERT_MODEL", "gemini-2.5-flash")


class BaseExpertAgent:
    def __init__(
        self,
        domain: str,
        wallet_id: str,
        wallet_address: Optional[str] = None,
        price: float = 0.003,
        model: Optional[str] = None,
    ):
        if not wallet_id:
            raise ValueError("wallet_id is required")

        self.domain = domain
        self.wallet_id = wallet_id
        self.wallet_address = wallet_address or wallet_id
        self.price = price
        self.model_name = model or AgentConfig.GEMINI_EXPERT_MODEL
        self.model = GeminiRestClient(model=self.model_name, timeout_seconds=45)

    def generate_402_response(self):
        """Returns x402 payment requirements."""
        payment_required = {
            "x402Version": 2,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "eip155:5042002",
                    "asset": "0x3600000000000000000000000000000000000000",
                    "amount": str(int(self.price * 1_000_000)),
                    "payTo": self.wallet_address,
                }
            ],
        }

        headers = {
            "X-Price": str(self.price),
            "X-Destination-Wallet": "arc:{}".format(self.wallet_address),
            "X-Chain": "arc-testnet",
            "X-Payment-Standard": "x402-nanopayments",
            "PAYMENT-REQUIRED": json.dumps(payment_required),
            "Content-Type": "application/json",
        }
        body = {
            "error": "Payment required",
            "price": self.price,
            "currency": "USDC",
            "destination": self.wallet_address,
            "domain": self.domain,
        }
        return headers, body

    async def verify_payment(self, signature: str, tx_hash: str) -> bool:
        """Verifies x402 payment proof with facilitator or Arc on-chain receipt."""
        if self._verify_via_facilitator(signature, tx_hash):
            return True
        return self._verify_via_onchain_transfer(tx_hash)

    def _verify_via_facilitator(self, signature: str, tx_hash: str) -> bool:
        if not AgentConfig.FACILITATOR_URL or not AgentConfig.CIRCLE_API_KEY:
            return False

        payload = {
            "signature": signature,
            "txHash": tx_hash,
            "amount": str(self.price),
            "destinationWallet": self.wallet_address,
            "chain": "arc-testnet",
        }

        try:
            response = requests.post(
                "{}/verify".format(AgentConfig.FACILITATOR_URL.rstrip("/")),
                json=payload,
                headers={
                    "Authorization": "Bearer {}".format(AgentConfig.CIRCLE_API_KEY),
                    "Content-Type": "application/json",
                },
                timeout=10,
            )
            if response.status_code != 200:
                return False
            try:
                data = response.json()
            except ValueError:
                return True
            return bool(data.get("isValid", data.get("success", data.get("verified", True))))
        except requests.RequestException as exc:
            print("Facilitator verify unavailable: {}".format(exc))
            return False

    def _verify_via_onchain_transfer(self, tx_hash: str) -> bool:
        if not tx_hash or not tx_hash.startswith("0x"):
            return False

        try:
            max_attempts = max(
                1,
                int(
                    AgentConfig.ARC_RECEIPT_MAX_WAIT_SECONDS
                    / max(AgentConfig.ARC_RECEIPT_POLL_SECONDS, 0.1)
                ),
            )

            receipt = None
            for attempt in range(max_attempts):
                response = requests.post(
                    AgentConfig.ARC_RPC_URL,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "eth_getTransactionReceipt",
                        "params": [tx_hash],
                    },
                    headers={"Content-Type": "application/json"},
                    timeout=10,
                )
                if response.status_code != 200:
                    return False

                body = response.json()
                receipt = body.get("result")
                if receipt:
                    break

                if attempt < max_attempts - 1:
                    time.sleep(AgentConfig.ARC_RECEIPT_POLL_SECONDS)

            if not receipt:
                return False
            if receipt.get("status") != "0x1":
                return False

            if not self.wallet_address.startswith("0x"):
                # If destination is non-EVM format, transaction success is the best available proof.
                return True

            receipt_to = (receipt.get("to") or "").lower()
            receipt_from = (receipt.get("from") or "").lower()
            expected_to = self.wallet_address.lower()

            # Arc wallet transfers may settle directly to the destination wallet without ERC20 logs.
            if receipt_to == expected_to:
                if AgentConfig.COORDINATOR_WALLET_ADDRESS and receipt_from:
                    return receipt_from == AgentConfig.COORDINATOR_WALLET_ADDRESS
                return True

            transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
            destination_topic = self._address_to_topic(self.wallet_address)
            required_units = int(round(self.price * 1_000_000))

            for log in receipt.get("logs", []):
                topics = log.get("topics", [])
                if len(topics) < 3:
                    continue
                if log.get("address", "").lower() != AgentConfig.ARC_USDC_TOKEN_ADDRESS:
                    continue
                if topics[0].lower() != transfer_topic:
                    continue
                if topics[2].lower() != destination_topic:
                    continue

                amount_hex = log.get("data", "0x0")
                amount = int(amount_hex, 16)
                if amount >= required_units:
                    return True

            return False
        except (requests.RequestException, ValueError, TypeError) as exc:
            print("On-chain receipt verification error: {}".format(exc))
            return False

    @staticmethod
    def _address_to_topic(address: str) -> str:
        return "0x{}{}".format("0" * 24, address.lower().replace("0x", ""))

    async def generate_answer(self, query: str) -> str:
        """Generates a domain-specific answer with Gemini Flash via SDK."""
        prompt = (
            "You are NanoPay's {domain} expert agent. "
            "Provide a concise, factual, and actionable response with 3-5 bullets "
            "and one short conclusion. Query: {query}"
        ).format(domain=self.domain, query=query)
        try:
            return self.model.generate_text(
                prompt=prompt,
                temperature=0.3,
                max_output_tokens=220,
            )
        except Exception as exc:
            print("Gemini expert fallback used: {}".format(exc))
            return (
                "- Domain: {domain}\n"
                "- Query received: {query}\n"
                "- AI model unavailable, returning structured fallback analysis.\n"
                "- Next step: rerun with a valid GEMINI_API_KEY for full synthesis.\n"
                "Conclusion: Payment was verified and the task reached the expert stage."
            ).format(domain=self.domain, query=query)


def create_agent_app(agent: BaseExpertAgent):
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "agent": agent.domain,
            "wallet": agent.wallet_address,
            "price": agent.price,
            "model": agent.model_name,
        }

    @app.get("/query")
    async def query(
        q: str,
        x_payment_signature: Optional[str] = Header(default=None),
        x_payment_tx: Optional[str] = Header(default=None),
        payment_signature: Optional[str] = Header(default=None),
    ):
        signature = x_payment_signature or payment_signature

        if not q or not q.strip():
            return Response(
                content=json.dumps({"error": "Query is required"}),
                status_code=400,
                headers={"Content-Type": "application/json"},
            )

        # 1) Require payment proof headers
        if not signature or not x_payment_tx:
            headers, body = agent.generate_402_response()
            return Response(content=json.dumps(body), status_code=402, headers=headers)

        # 2) Verify payment through facilitator
        is_paid = await agent.verify_payment(signature, x_payment_tx)
        if not is_paid:
            headers, body = agent.generate_402_response()
            return Response(content=json.dumps(body), status_code=402, headers=headers)

        # 3) Return paid answer
        answer = await agent.generate_answer(q)
        return {
            "answer": answer,
            "agent": agent.domain,
            "status": "paid",
            "tx_hash": x_payment_tx,
        }

    return app
