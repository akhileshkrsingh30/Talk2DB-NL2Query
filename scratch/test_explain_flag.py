import requests
import json
import time

BASE_URL = "http://localhost:8080"

def test_process_query():
    print("\n=== Testing /queries/process with explain=True (explicit) ===")
    payload = {
        "query": "Show all tables or list information about databases",
        "explain": True
    }
    
    start_time = time.time()
    response = requests.post(f"{BASE_URL}/queries/process", json=payload)
    elapsed = time.time() - start_time
    
    print(f"Status Code: {response.status_code}")
    print(f"Elapsed Time: {elapsed:.2f}s")
    
    if response.status_code == 200:
        data = response.json()
        print("SQL Queries Generated:")
        for sql in data.get("sql_queries", []):
            print(f"  - {sql.get('sql')}")
        print(f"Results Count: {len(data.get('results', []))}")
        explanation = data.get("explanation")
        print(f"Explanation: {explanation}")
        assert explanation is not None and explanation != "", "Explanation should not be empty when explain=True!"
        print("PASS: explain=True returned an explanation.")
    else:
        print(f"FAIL: {response.text}")

    print("\n=== Testing /queries/process with explain=False ===")
    payload = {
        "query": "Show all tables or list information about databases",
        "explain": False
    }
    
    start_time = time.time()
    response = requests.post(f"{BASE_URL}/queries/process", json=payload)
    elapsed = time.time() - start_time
    
    print(f"Status Code: {response.status_code}")
    print(f"Elapsed Time: {elapsed:.2f}s")
    
    if response.status_code == 200:
        data = response.json()
        print("SQL Queries Generated:")
        for sql in data.get("sql_queries", []):
            print(f"  - {sql.get('sql')}")
        print(f"Results Count: {len(data.get('results', []))}")
        explanation = data.get("explanation")
        print(f"Explanation: {explanation}")
        assert explanation is None or explanation == "", "Explanation should be empty or None when explain=False!"
        print("PASS: explain=False returned empty/None explanation.")
    else:
        print(f"FAIL: {response.text}")

def test_batch_process_query():
    print("\n=== Testing /queries/process-batch with mixed explain values ===")
    payload = {
        "queries": [
            {
                "query": "Show all tables",
                "explain": True
            },
            {
                "query": "Show all tables",
                "explain": False
            }
        ],
        "parallel": False
    }
    
    start_time = time.time()
    response = requests.post(f"{BASE_URL}/queries/process-batch", json=payload)
    elapsed = time.time() - start_time
    
    print(f"Status Code: {response.status_code}")
    print(f"Elapsed Time: {elapsed:.2f}s")
    
    if response.status_code == 200:
        data = response.json()
        results = data.get("results", [])
        print(f"Batch returned {len(results)} results.")
        
        # Check first query (explain=True)
        q1_explanation = results[0].get("explanation")
        print(f"Query 1 (explain=True) Explanation: {q1_explanation}")
        assert q1_explanation is not None and q1_explanation != "", "First query explanation should not be empty!"
        
        # Check second query (explain=False)
        q2_explanation = results[1].get("explanation")
        print(f"Query 2 (explain=False) Explanation: {q2_explanation}")
        assert q2_explanation is None or q2_explanation == "", "Second query explanation should be empty/None!"
        
        print("PASS: Batch query process respected individual explain flags.")
    else:
        print(f"FAIL: {response.text}")

if __name__ == "__main__":
    test_process_query()
    test_batch_process_query()
