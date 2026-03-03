import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

PB_URL = "http://localhost:8090"
EMAIL = "admin@loom.local"
PASS = "loom_secure_password"

def provision():
    print(f"Authenticating with {PB_URL}...")
    auth_url = f"{PB_URL}/api/collections/_superusers/auth-with-password"
    payload = {"identity": EMAIL, "password": PASS}
    
    resp = requests.post(auth_url, json=payload)
    if resp.status_code != 200:
        print(f"Auth failed: {resp.text}")
        return
    
    token = resp.json().get("token")
    headers = {"Authorization": token, "Content-Type": "application/json"}
    
    collections = [
        {
            "name": "projects",
            "type": "base",
            "schema": [
                {"name": "owner", "type": "relation", "options": {"collectionId": "_pb_users_auth_", "maxSelect": 1}},
                {"name": "title", "type": "text", "required": True},
                {"name": "share_token", "type": "text", "required": True},
                {"name": "is_archived", "type": "bool"}
            ],
            "listRule": "", "viewRule": "", "createRule": "", "updateRule": "", "deleteRule": ""
        },
        {
            "name": "video_assets",
            "type": "base",
            "schema": [
                {"name": "project", "type": "relation", "options": {"collectionId": "projects", "maxSelect": 1}},
                {"name": "file", "type": "file", "options": {"maxSelect": 1}},
                {"name": "duration", "type": "number"},
                {"name": "waveform_data", "type": "json"},
                {"name": "status", "type": "select", "options": {"values": ["processing", "ready", "error"]}}
            ],
            "listRule": "", "viewRule": "", "createRule": "", "updateRule": "", "deleteRule": ""
        },
        {
            "name": "comments",
            "type": "base",
            "schema": [
                {"name": "project", "type": "relation", "options": {"collectionId": "projects", "maxSelect": 1}},
                {"name": "video_asset", "type": "relation", "options": {"collectionId": "video_assets", "maxSelect": 1}},
                {"name": "timestamp", "type": "number"},
                {"name": "author_name", "type": "text"},
                {"name": "body", "type": "text"},
                {"name": "is_resolved", "type": "bool"}
            ],
            "listRule": "", "viewRule": "", "createRule": "", "updateRule": "", "deleteRule": ""
        }
    ]
    
    for coll in collections:
        print(f"Creating collection {coll['name']}...")
        create_resp = requests.post(f"{PB_URL}/api/collections", json=coll, headers=headers)
        if create_resp.status_code in [200, 201]:
            print(f"  SUCCESS")
        else:
            print(f"  FAILED: {create_resp.text}")

if __name__ == "__main__":
    provision()
