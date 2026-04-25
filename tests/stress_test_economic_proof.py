import os
import requests
import json
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
TX_HASHES_TXT_PATH = OUTPUT_DIR / "stress-test-tx-hashes.txt"


def _save_tx_hashes(tx_hashes):
    """Persist unique transaction hashes for post-run proof artifacts."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ordered_unique = list(dict.fromkeys(tx_hashes))
    TX_HASHES_TXT_PATH.write_text("\n".join(ordered_unique) + ("\n" if ordered_unique else ""), encoding="utf-8")
    return ordered_unique

def test_economic_proof():
    """
    End-to-End Stress Test for NanoPay.
    Goal: Prove 50+ real transactions on Arc L1.
    """
    print("Starting NanoPay Economic Proof Stress Test...")

    # Use a query designed to trigger a massive decomposition
    demo_query = {
        "query": "Comprehensive analysis of AI regulation across G20 nations: legal frameworks, financial market implications, biotech and pharma regulatory impacts, patent filing trends, and compliance requirements for AI-driven medical devices",
        "budget_cap": 1.00,
        "target_transactions": 52,
    }

    try:
        response = requests.post(
            "http://localhost:8000/api/research",
            json=demo_query
        )

        if response.status_code != 200:
            print(f"Request failed with status {response.status_code}")
            print(response.text)
            return

        data = response.json()
        txs = data.get("details", [])
        count = len(txs)
        tx_hashes = [tx.get("tx_hash") for tx in txs if tx.get("tx_hash")]
        unique_hashes = _save_tx_hashes(tx_hashes)
        total_spent = float(data.get("summary", {}).get("total_spent", 0))
        per_action = (total_spent / count) if count else 0

        print("\n--- Economic Proof Summary ---")
        print(f"Total Transactions: {count}")
        print(f"Unique Tx Hashes: {len(unique_hashes)}")
        print(f"Tx Hash Artifact: {TX_HASHES_TXT_PATH}")
        print(f"Total Spent: {total_spent} USDC")
        print(f"Average Cost/Action: {per_action:.6f} USDC")
        print(f"Agents Used: {data.get('summary', {}).get('agents_used', [])}")

        if count >= 50 and len(unique_hashes) >= 50 and per_action <= 0.01:
            print("\nSUCCESS: 50+ unique transactions and <= $0.01/action achieved.")
        else:
            print("\nFAILED requirement checks.")
            if count < 50:
                print(f"- transaction_count={count} (need >= 50)")
            if len(unique_hashes) < 50:
                print(f"- unique_tx_hashes={len(unique_hashes)} (need >= 50)")
            if per_action > 0.01:
                print(f"- avg_cost={per_action:.6f} (need <= 0.010000)")

        # Sample check for Arc Explorer links
        if txs:
            sample_tx = txs[0]["tx_hash"]
            print(f"Sample Transaction Proof: https://testnet.arcscan.app/tx/{sample_tx}")

    except Exception as e:
        print(f"Stress test crashed: {e}")

if __name__ == "__main__":
    test_economic_proof()
