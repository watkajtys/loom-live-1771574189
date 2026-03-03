import os
import time
import requests
import subprocess
import shutil
from pathlib import Path

# Load keys
github_token = None
jules_key = None
if os.path.exists(".env"):
    with open(".env", "r") as f:
        for line in f:
            if line.startswith("GITHUB_TOKEN="):
                github_token = line.strip().split("=", 1)[1]
            if line.startswith("JULES_API_KEY="):
                jules_key = line.strip().split("=", 1)[1]

if not github_token or not jules_key:
    print("Error: Missing keys")
    exit(1)

TEST_DIR = Path(f"tmp_test_git_{int(time.time())}")
JULES_API = "https://jules.googleapis.com/v1alpha"

def run(cmd, cwd=TEST_DIR):
    print(f"> {cmd}")
    subprocess.run(cmd, cwd=cwd, shell=True, check=True)

# 1. Setup Local Repo
TEST_DIR.mkdir()

run("git init")
run("echo Initial Content > README.md")
run("git add .")
run("git commit -m \"Initial commit\"")

# 2. Create GitHub Repo
repo_name = f"loom-test-{int(time.time())}"
print(f"Creating GitHub Repo: {repo_name}...")

resp = requests.post(
    "https://api.github.com/user/repos",
    headers={"Authorization": f"token {github_token}"},
    json={"name": repo_name, "private": False}
)
if not resp.ok:
    print(f"GitHub Error: {resp.text}")
    exit(1)

repo_data = resp.json()
clone_url = repo_data["clone_url"]
owner = repo_data["owner"]["login"]
auth_url = clone_url.replace("https://", f"https://{github_token}@")

# 3. Push to GitHub
print("Pushing to GitHub...")
run(f"git remote add origin {auth_url}")
run("git branch -M main")
run("git push -u origin main")

# 4. Check Jules Sources
print("Checking Jules Sources for new repo...")
expected_source_name = f"sources/github/{owner}/{repo_name}"
found_source = None

for attempt in range(12): # Poll for 1 minute (12 * 5s)
    print(f"Attempt {attempt+1}/12: Listing sources...")
    
    page_token = None
    while True:
        params = {}
        if page_token:
            params["pageToken"] = page_token
            
        sources_resp = requests.get(
            f"{JULES_API}/sources",
            headers={"X-Goog-Api-Key": jules_key},
            params=params
        )
        
        if not sources_resp.ok:
            print(f"Jules Sources API Error: {sources_resp.text}")
            break 
            
        sources_data = sources_resp.json()
        sources = sources_data.get("sources", [])
        
        for source in sources:
            if source.get("name") == expected_source_name:
                found_source = source
                break
        
        if found_source:
            break
            
        page_token = sources_data.get("nextPageToken")
        if not page_token:
            break
            
    if found_source:
        print(f"Found Source: {found_source['name']}")
        break
        
    time.sleep(5)

if not found_source:
    print(f"Error: Source {expected_source_name} not found after polling.")
    print("Proceeding with constructed source name...")
    found_source = {"name": expected_source_name}

# 5. Call Jules API (Create Session)
print("Creating Jules Session...")
payload = {
    "prompt": "Create a new file named 'success.txt' with the text 'Jules was here'.",
    "sourceContext": {
        "source": found_source["name"],
        "githubRepoContext": {
            "startingBranch": "main"
        }
    }
}

print(f"Payload: {payload}")

resp = requests.post(
    f"{JULES_API}/sessions",
    headers={"X-Goog-Api-Key": jules_key, "Content-Type": "application/json"},
    json=payload
)

if not resp.ok:
    print(f"Jules API Error ({resp.status_code}): {resp.text}")
    # Try snake_case if camelCase failed?
    # No, let's just fail for now to read the error.
    exit(1)

session = resp.json()
session_name = session.get("name")
print(f"Session Created: {session_name}")

# 6. Poll Session Status
print("Waiting for Jules to finish task...")
MAX_POLL_ATTEMPTS = 1440  # 4 hours (1440 * 10s)
for attempt in range(MAX_POLL_ATTEMPTS):
    time.sleep(10)
    try:
        status_resp = requests.get(
            f"{JULES_API}/{session_name}",
            headers={"X-Goog-Api-Key": jules_key}
        )
        if not status_resp.ok:
            print(f"Status Check Error: {status_resp.text}")
            continue
            
        session_data = status_resp.json()
        state = session_data.get("state")
        print(f"Status (Attempt {attempt+1}/{MAX_POLL_ATTEMPTS}): {state}")
        
        if state == "COMPLETED" or state == "SUCCEEDED":
            print("Task Completed!")
            print(session_data)
            break
        if state in ["FAILED", "ERROR", "CANCELLED"]:
            print("Task Failed!")
            print(session_data)
            exit(1)
    except Exception as e:
        print(f"Polling Exception: {e}")
        continue
else:
    print("Timeout: Jules task took too long.")
    exit(1)

# 7. Verify Patch
print("Verifying Patch...")
outputs = session_data.get("outputs", [])
if not outputs:
    print("FAILURE! No outputs found.")
    exit(1)

found_patch = False
for output in outputs:
    change_set = output.get("changeSet", {})
    git_patch = change_set.get("gitPatch", {})
    patch_content = git_patch.get("unidiffPatch", "")
    
    if "Jules was here" in patch_content:
        found_patch = True
        print("SUCCESS! Patch received with expected content.")
        print(patch_content)
        break

if not found_patch:
    print("FAILURE! Patch did not contain expected content.")
    exit(1)
