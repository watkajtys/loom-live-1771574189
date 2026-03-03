import os
import requests
import json

from dotenv import load_dotenv
load_dotenv(override=True)

api_key = os.getenv("STITCH_API_KEY")

url = "https://stitch.googleapis.com/mcp"
headers = {
    "X-Goog-Api-Key": api_key,
    "Content-Type": "application/json"
}

payload = {
    "jsonrpc": "2.0",
    "method": "tools/list",
    "id": 1
}

resp = requests.post(url, headers=headers, json=payload)
print(json.dumps(resp.json(), indent=2))
