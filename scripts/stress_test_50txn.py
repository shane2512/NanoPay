import requests
import concurrent.futures
import time

API_URL = "http://localhost:8000/api/research"
QUERY = "Explain the impact of AI on global finance and biotech."
BUDGET = 0.5
NUM_TXN = 50

def run_research(i):
    payload = {
        "query": f"{QUERY} [Test #{i+1}]",
        "budget_cap": BUDGET,
        "target_transactions": 12
    }
    try:
        start = time.time()
        response = requests.post(API_URL, json=payload, timeout=60)
        elapsed = time.time() - start
        data = response.json()
        spent = data.get("summary", {}).get("total_spent", 0)
        print(f"Request {i+1}: {response.status_code} - {data.get('status', '')} | Spent: ${spent} | Time: {elapsed:.2f}s")
        return spent
    except Exception as e:
        print(f"Request {i+1}: ERROR - {e}")
        return 0

if __name__ == "__main__":
    total_spent = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_TXN) as executor:
        futures = [executor.submit(run_research, i) for i in range(NUM_TXN)]
        for future in concurrent.futures.as_completed(futures):
            total_spent += future.result()
    print(f"\nTotal gas/fees spent for {NUM_TXN} transactions: ${total_spent:.4f}")
