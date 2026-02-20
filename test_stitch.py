import os
import requests
import json

# Manually parse .env since python-dotenv might not be installed in the shell environment yet
api_key = None
if os.path.exists(".env"):
    with open(".env", "r") as f:
        for line in f:
            if line.startswith("STITCH_API_KEY="):
                api_key = line.strip().split("=", 1)[1]
                break

if not api_key:
    print("Error: STITCH_API_KEY not found in .env")
    exit(1)

url = "https://stitch.googleapis.com/mcp"
headers = {
    "Content-Type": "application/json",
    "X-Goog-Api-Key": api_key
}

# 1. Test: List Tools
payload = {
    "jsonrpc": "2.0",
    "method": "tools/list",
    "id": 1
}

print(f"Testing Stitch API Connection to {url}...")
try:
    response = requests.post(url, json=payload, headers=headers, timeout=10)
    print(f"Status Code: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print("Connection Successful!")
        print("Available Tools:")
        tools = data.get("result", {}).get("tools", [])
        for tool in tools:
            if tool.get("name") == "generate_screen_from_text":
                print(f"\n--- TOOL: {tool.get('name')} ---")
                print(json.dumps(tool, indent=2))
    else:
        print(f"Error: {response.text}")

except Exception as e:
    print(f"Exception: {e}")
