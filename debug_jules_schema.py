import os
import requests
import json

api_key = None
if os.path.exists(".env"):
    with open(".env", "r") as f:
        for line in f:
            if line.startswith("JULES_API_KEY="):
                api_key = line.strip().split("=", 1)[1]

if not api_key:
    print("Error: Missing JULES_API_KEY")
    exit(1)

url = "https://jules.googleapis.com/v1alpha/sessions"
headers = {
    "X-Goog-Api-Key": api_key,
    "Content-Type": "application/json"
}

session_id = "sessions/16274083389654299536"
url = f"https://jules.googleapis.com/v1alpha/{session_id}"

print(f"Getting Session {session_id}...")
try:
    response = requests.get(url, headers=headers)
    print(f"Status Code: {response.status_code}")
    
    if response.status_code == 200:
        print(json.dumps(response.json(), indent=2))
    else:
        print(f"Error: {response.text}")
except Exception as e:
    print(f"Exception: {e}")
