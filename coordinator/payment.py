import os
import requests
import json
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

class CirclePaymentClient:
    """
    Handles the x402 payment flow using the real Circle Nanopayments API.
    NO MOCKS: All transactions are settled on Arc.
    """
    def __init__(self):
        self.api_key = os.getenv("CIRCLE_API_KEY")
        self.gateway_api_url = (
            os.getenv("CIRCLE_GATEWAY_API_URL")
            or os.getenv("CIRCLE_FACILITATOR_URL")
            or "https://gateway-api-testnet.circle.com"
        )
        self.coordinator_wallet_id = os.getenv("COORDINATOR_WALLET_ID")
        self.coordinator_wallet_address = os.getenv("COORDINATOR_WALLET_ADDRESS")
        self.timeout_seconds = float(os.getenv("CIRCLE_HTTP_TIMEOUT_SECONDS", "25"))
        self.project_root = Path(__file__).resolve().parents[1]
        self.transfer_script = self.project_root / "scripts" / "circle-transfer.mjs"

        if not self.api_key:
            raise ValueError("CIRCLE_API_KEY is required in .env")
        if not self.coordinator_wallet_id and not self.coordinator_wallet_address:
            raise ValueError(
                "COORDINATOR_WALLET_ID or COORDINATOR_WALLET_ADDRESS is required in .env"
            )

    def execute_x402_payment(self, endpoint: str, query: str):
        """
        The full x402 handshake:
        1. Initial Request -> Receive 402
        2. Authorize USDC transfer via Circle
        3. Submit to Nanopayments API
        4. Retry request with payment proof -> Receive Answer
        """
        # --- Step 1: Initial Request ---
        # Expecting HTTP 402 Payment Required
        response = requests.get(endpoint, params={"q": query}, timeout=self.timeout_seconds)

        if response.status_code != 402:
            # If it's 200, the agent might be open or already paid
            if response.status_code == 200:
                return {"answer": response.json().get("answer"), "tx_hash": "already_paid", "amount": 0}
            raise Exception(f"Expected 402 Payment Required, got {response.status_code}")

        # Extract payment details from headers
        price = response.headers.get("X-Price")
        destination_wallet = response.headers.get("X-Destination-Wallet")

        if (not price or not destination_wallet) and response.headers.get("PAYMENT-REQUIRED"):
            try:
                required = json.loads(response.headers.get("PAYMENT-REQUIRED", "{}"))
                accepts = required.get("accepts", [])
                if accepts:
                    option = accepts[0]
                    if not destination_wallet:
                        destination_wallet = option.get("payTo")
                    if not price and option.get("amount"):
                        # Convert 6-decimal USDC base units to decimal string.
                        price = str(float(option["amount"]) / 1_000_000)
            except ValueError:
                pass

        if not price or not destination_wallet:
            raise Exception("Missing x402 headers (X-Price or X-Destination-Wallet)")

        # --- Step 2 & 3: Authorization and Nanopayment ---
        # In a production SDK, we would use the Circle SDK to sign an EIP-3009.
        # For the hackathon, we use the Circle Nanopayments API to authorize the transfer.

        destination_address = destination_wallet.replace("arc:", "")
        tx_id = None
        try:
            payment_data = self._authorize_via_facilitator(price, destination_address)
            signature = payment_data["signature"]
            tx_hash = payment_data["tx_hash"]
            tx_id = payment_data.get("tx_id")
        except Exception as exc:
            # Fallback path still performs a real Arc USDC settlement with Circle wallets.
            print("Facilitator authorize unavailable, using Circle transfer fallback: {}".format(exc))
            payment_data = self._authorize_via_circle_transfer(price, destination_address)
            signature = payment_data["tx_id"]
            tx_hash = payment_data["tx_hash"]
            tx_id = payment_data["tx_id"]

        # --- Step 4: Retry with Proof ---
        headers = {
            "X-Payment-Signature": signature,
            "PAYMENT-SIGNATURE": signature,
            "X-Payment-Tx": tx_hash,
        }
        if tx_id:
            headers["X-Payment-Tx-Id"] = tx_id

        final_response = requests.get(
            endpoint,
            params={"q": query},
            headers=headers,
            timeout=self.timeout_seconds,
        )

        if final_response.status_code != 200:
            raise Exception(f"Failed to retrieve answer after payment: {final_response.status_code}")

        return {
            "answer": final_response.json().get("answer"),
            "tx_hash": tx_hash,
            "amount": price,
        }

    def _authorize_via_facilitator(self, price: str, destination_address: str):
        payment_payload = {
            "amount": price,
            "currency": "USDC",
            "destination": destination_address,
            "sender": self.coordinator_wallet_id,
            "blockchain": "arc-testnet",
        }

        auth_response = requests.post(
            "{}/authorize".format(self.gateway_api_url.rstrip("/")),
            json=payment_payload,
            headers={
                "Authorization": "Bearer {}".format(self.api_key),
                "Content-Type": "application/json",
            },
            timeout=self.timeout_seconds,
        )

        if auth_response.status_code != 200:
            raise Exception(
                "Facilitator authorize failed ({}): {}".format(
                    auth_response.status_code,
                    auth_response.text,
                )
            )

        body = auth_response.json()
        signature = (
            body.get("signature")
            or body.get("paymentSignature")
            or body.get("authorization")
        )
        tx_hash = body.get("txHash") or body.get("transactionHash")
        tx_id = body.get("id")

        if not signature:
            raise Exception("Facilitator response missing signature")
        if not tx_hash:
            raise Exception("Facilitator response missing tx hash")

        return {
            "signature": signature,
            "tx_hash": tx_hash,
            "tx_id": tx_id,
        }

    def _authorize_via_circle_transfer(self, price: str, destination_address: str):
        if not self.transfer_script.exists():
            raise Exception("Missing transfer helper script: {}".format(self.transfer_script))

        cmd = [
            "node",
            "--env-file=.env",
            str(self.transfer_script),
            "--destination",
            destination_address,
            "--amount",
            price,
        ]
        if self.coordinator_wallet_address:
            cmd.extend(["--sender", self.coordinator_wallet_address])

        result = subprocess.run(
            cmd,
            cwd=str(self.project_root),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

        if result.returncode != 0:
            raise Exception(
                "circle-transfer failed: {}".format(
                    (result.stderr or result.stdout).strip()
                )
            )

        try:
            body = json.loads(result.stdout.strip())
        except ValueError as exc:
            raise Exception("Invalid circle-transfer response: {}".format(exc))

        tx_id = body.get("txId")
        tx_hash = body.get("txHash")
        if not tx_id or not tx_hash:
            raise Exception("circle-transfer response missing txId or txHash")

        return {
            "tx_id": tx_id,
            "tx_hash": tx_hash,
        }
