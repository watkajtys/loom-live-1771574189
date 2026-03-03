import os
import requests
import json
import time
from dotenv import load_dotenv

load_dotenv(override=True)

api_key = os.getenv("STITCH_API_KEY")
url = "https://stitch.googleapis.com/mcp"
headers = {
    "X-Goog-Api-Key": api_key,
    "Content-Type": "application/json"
}

def call_mcp(method, args):
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": method,
            "arguments": args
        },
        "id": 1
    }
    resp = requests.post(url, headers=headers, json=payload)
    return resp.json()

print("--- Creating Project ---")
proj_resp = call_mcp("create_project", {"title": "API Test Project"})
print(json.dumps(proj_resp, indent=2))

# Extract project ID
try:
    # Based on current stitch.py logic
    result = proj_resp.get("result", {})
    project_id = None
    for block in result.get("content", []):
        if block.get("type") == "text":
            inner = json.loads(block.get("text", ""))
            name = inner.get("name", "")
            project_id = name.split("/")[1]
            break
    if not project_id: raise Exception("Project ID not found")
except Exception as e:
    print(f"Failed to parse project ID: {e}")
    exit(1)

print(f"\n--- Generating Screen in Project {project_id} ---")
gen_resp = call_mcp("generate_screen_from_text", {
    "projectId": project_id,
    "prompt": "A simple landing page for a video review tool with a large video player and a timeline.",
    "deviceType": "DESKTOP"
})

print("RAW GENERATION RESPONSE:")
print(json.dumps(gen_resp, indent=2))

# Check if content exists
result = gen_resp.get("result", {})
content = result.get("content", [])
if not content:
    print("\nWARNING: No content blocks returned in direct response.")
    print("Attempting list_screens fallback in 10s...")
    time.sleep(10)
    list_resp = call_mcp("list_screens", {"projectId": project_id})
    print("\nRAW LIST_SCREENS RESPONSE:")
    print(json.dumps(list_resp, indent=2))
