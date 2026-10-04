"""Test email verification with longer wait."""
import sys, time, requests
sys.path.insert(0, ".")

from src.snov.client import SnovClient, BASE_URL
snov = SnovClient()
token = snov._get_token()
headers = {"Authorization": f"Bearer {token}"}

# Start verification
print("Starting email verification...")
r = requests.post(f"{BASE_URL}/v2/email-verification/start", headers=headers,
                  json={"emails": ["frode.arntsen@salmar.no"]}, timeout=15)
print(f"Start: {r.status_code} {r.text[:200]}")

if r.ok:
    task_hash = r.json().get("data", {}).get("task_hash")
    print(f"task_hash: {task_hash}")

    # Poll for up to 60 seconds
    for i in range(12):
        time.sleep(5)
        r2 = requests.get(f"{BASE_URL}/v2/email-verification/result",
                         headers=headers, params={"task_hash": task_hash}, timeout=15)
        data = r2.json()
        print(f"  Poll {i+1}: {r2.status_code} {str(data)[:200]}")
        if data.get("data"):
            print(f"  DONE: {data['data']}")
            break
