import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

PB_URL = "http://loom-pocketbase:8090"
EMAIL = "admin@loom.local"
PASS = "loom_secure_password"

def provision():
    creds = [
        ("admin@loom.local", "loom_secure_password"),
        ("test@test.com", "1234567890")
    ]
    
    endpoints = [
        f"{PB_URL}/api/collections/_superusers/auth-with-password",
        f"{PB_URL}/api/admins/auth-with-password"
    ]
    
    id_keys = ["identity", "email"]
    
    token = None
    headers = None
    
    for email, password in creds:
        for auth_url in endpoints:
            for id_key in id_keys:
                print(f"Trying auth for {email} via {auth_url} ({id_key})...")
                payload = {id_key: email, "password": password}
                try:
                    resp = requests.post(auth_url, json=payload, timeout=5)
                    if resp.status_code == 200:
                        print(f"  SUCCESS for {email}")
                        token = resp.json().get("token")
                        headers = {"Authorization": token, "Content-Type": "application/json"}
                        break
                    else:
                        print(f"  FAILED ({resp.status_code})")
                except Exception as e:
                    print(f"  ERROR: {e}")
            if token: break
        if token: break
    
    if not token:
        print("All auth variants failed.")
        return
    
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
