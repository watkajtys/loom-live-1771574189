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

candidates = [
    {"source": "sources/github/watkajtys/repo"},
    {"repository": "sources/github/watkajtys/repo"},
    {"github": {"url": "https://github.com/watkajtys/repo"}},
    {"github_repository": {"url": "https://github.com/watkajtys/repo"}},
    {"git_repository": {"url": "https://github.com/watkajtys/repo"}},
    {"code_repository": {"url": "https://github.com/watkajtys/repo"}}
]

print("Probing Schema...")
for c in candidates:
    key_name = list(c.keys())[0]
    payload = {
        "prompt": "test",
        "sourceContext": c
    }
    
    resp = requests.post(url, headers=headers, json=payload)
    if resp.status_code == 400:
        err = resp.json().get("error", {}).get("message", "")
        # Check for unknown name error
        target_str = "Unknown name \"" + key_name + "\""
        if target_str in err:
            print(f"[X] {key_name}: Unknown Field")
        else:
            print(f"[!] {key_name}: POTENTIAL MATCH! Error: {err}")
    else:
        print(f"[?] {key_name}: Status {resp.status_code}")
