import os
import requests
import json

api_key = None
if os.path.exists(".env"):
    with open(".env", "r") as f:
        for line in f:
            if line.startswith("JULES_API_KEY="):
                api_key = line.strip().split("=", 1)[1]

url = "https://jules.googleapis.com/v1alpha/sessions"
headers = {
    "X-Goog-Api-Key": api_key,
    "Content-Type": "application/json"
}

repo = "https://github.com/watkajtys/ouroboros-test-1771557814" # Use one of our created ones

candidates = [
    f"sources/github/watkajtys/ouroboros-test-1771557814",
    repo,
    f"git+{repo}",
    f"projects/-/locations/global/connections/github/repositories/watkajtys/ouroboros-test-1771557814"
]

print("Probing Source Values...")
for val in candidates:
    payload = {
        "prompt": "test",
        "sourceContext": {
            "source": val,
            # Maybe it needs branch too?
            # "githubRepoContext": {"startingBranch": "main"} 
        }
    }
    
    resp = requests.post(url, headers=headers, json=payload)
    print(f"Value: {val[:50]}... | Status: {resp.status_code} | Msg: {resp.json().get('error', {}).get('message', '')}")
