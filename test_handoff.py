import os
import time
import requests
import subprocess
import shutil
import json
from pathlib import Path

# --- Configuration ---
TEST_DIR = Path(f"tmp_handoff_{int(time.time())}")
APP_SRC_DIR = Path("app")
JULES_API = "https://jules.googleapis.com/v1alpha"
STITCH_API = "https://stitch.googleapis.com/mcp"

# Load keys
keys = {}
if os.path.exists(".env"):
    with open(".env", "r") as f:
        for line in f:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                keys[k] = v

required_keys = ["GITHUB_TOKEN", "JULES_API_KEY", "STITCH_API_KEY", "STITCH_PROJECT_ID"]
if any(k not in keys for k in required_keys):
    print(f"Error: Missing keys. Need {required_keys}")
    exit(1)

github_token = keys["GITHUB_TOKEN"]
jules_key = keys["JULES_API_KEY"]
stitch_key = keys["STITCH_API_KEY"]
stitch_project_id = keys["STITCH_PROJECT_ID"]

def run(cmd, cwd=TEST_DIR):
    print(f"[{cwd}] > {cmd}")
    subprocess.run(cmd, cwd=cwd, shell=True, check=True)

# --- 1. Setup Test Environment ---
print("--- Step 1: Setting up Test Environment ---")
if TEST_DIR.exists():
    shutil.rmtree(TEST_DIR)
TEST_DIR.mkdir()

# Copy app (excluding node_modules and .git for speed/cleanliness)
# Actually, copying node_modules saves 'npm install' time.
print("Copying app directory...")
def ignore_patterns(path, names):
    return [n for n in names if n == '.git'] # Keep node_modules

shutil.copytree(APP_SRC_DIR, TEST_DIR / "app", ignore=ignore_patterns)

# Initialize Git in Test Dir
run("git init", cwd=TEST_DIR)
run('git config user.email "test@example.com"', cwd=TEST_DIR)
run('git config user.name "Test User"', cwd=TEST_DIR)
run("git add .", cwd=TEST_DIR)
run('git commit -m "Initial commit of app"', cwd=TEST_DIR)

# Create Remote Repo
repo_name = f"loom-handoff-{int(time.time())}"
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

print("Pushing to GitHub...")
run(f"git remote add origin {auth_url}", cwd=TEST_DIR)
run("git branch -M main", cwd=TEST_DIR)
run("git push -u origin main", cwd=TEST_DIR)

# --- 2. Stitch Design Generation ---
print("\n--- Step 2: Stitch Design Generation ---")
prompt = "A simple login screen with a username field, password field, and a blue 'Log In' button. Cyberpunk style."
stitch_payload = {
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
        "name": "generate_screen_from_text",
        "arguments": {
            "projectId": stitch_project_id,
            "prompt": prompt
        }
    },
    "id": 1
}

print(f"Calling Stitch (timeout=300s)...")
# Check if we can reuse a previous design to save time? No, let's allow it to run.
stitch_resp = requests.post(
    STITCH_API, 
    json=stitch_payload, 
    headers={"Content-Type": "application/json", "X-Goog-Api-Key": stitch_key}, 
    timeout=300
)

if not stitch_resp.ok:
    print(f"Stitch Failed: {stitch_resp.text}")
    print("Using Fallback HTML...")
    html_url = None
    html_content = "<html><body><div class='bg-slate-900 text-white min-h-screen flex items-center justify-center'><div class='p-8 bg-slate-800 rounded-xl'><h1 class='text-2xl mb-4'>Login</h1><input class='block w-full mb-4 p-2 bg-slate-700' placeholder='Username'/><input class='block w-full mb-4 p-2 bg-slate-700' type='password' placeholder='Password'/><button class='w-full bg-blue-600 p-2 rounded'>Log In</button></div></div></body></html>"
else:
    stitch_data = stitch_resp.json()
    html_url = None
    if stitch_data.get("result", {}).get("isError"):
        print(f"Stitch returned error: {json.dumps(stitch_data)}")
        print("Using Fallback HTML...")
        html_content = "<html><body><div class='bg-slate-900 text-white min-h-screen flex items-center justify-center'><div class='p-8 bg-slate-800 rounded-xl'><h1 class='text-2xl mb-4'>Login</h1><input class='block w-full mb-4 p-2 bg-slate-700' placeholder='Username'/><input class='block w-full mb-4 p-2 bg-slate-700' type='password' placeholder='Password'/><button class='w-full bg-blue-600 p-2 rounded'>Log In</button></div></div></body></html>"
    else:
        try:
            content = stitch_data["result"]["content"]
            for block in content:
                if block["type"] == "text":
                    inner = json.loads(block["text"])
                    screens = inner.get("outputComponents", [{}])[0].get("design", {}).get("screens", [])
                    if screens and "htmlCode" in screens[0]:
                        html_url = screens[0]["htmlCode"].get("downloadUrl")
                        break
        except Exception as e:
            print(f"Failed to parse Stitch response: {e}")
            print(json.dumps(stitch_data, indent=2))
            exit(1)

        if not html_url:
            print("No HTML URL found in Stitch response.")
            exit(1)

        print(f"Downloading HTML from {html_url}...")
        html_content = requests.get(html_url).text

design_file = TEST_DIR / "app/design/latest_design.html"
design_file.parent.mkdir(parents=True, exist_ok=True)
with open(design_file, "w", encoding="utf-8") as f:
    f.write(html_content)

print("Committing Design...")
run("git add app/design/latest_design.html", cwd=TEST_DIR)
run('git commit -m "Add Stitch Design"', cwd=TEST_DIR)
run("git push origin main", cwd=TEST_DIR)

# --- 3. Jules Implementation ---
print("\n--- Step 3: Jules Implementation ---")
# Poll for source availability
expected_source = f"sources/github/{owner}/{repo_name}"
print(f"Waiting for source {expected_source}...")
for attempt in range(12):
    time.sleep(5)
    source_found = False
    page_token = None
    while True:
        params = {"pageToken": page_token} if page_token else {}
        resp = requests.get(f"{JULES_API}/sources", headers={"X-Goog-Api-Key": jules_key}, params=params)
        if not resp.ok:
            break
        data = resp.json()
        if any(s.get("name") == expected_source for s in data.get("sources", [])):
            source_found = True
            break
        page_token = data.get("nextPageToken")
        if not page_token:
            break
            
    if source_found:
        print("Source found!")
        break
else:
    print("Source not found, proceeding optimistically...")

# Create Session
jules_prompt = f"Implement the design found in app/design/latest_design.html into app/src/App.tsx using React and Tailwind CSS. Ensure it builds."
payload = {
    "prompt": jules_prompt,
    "sourceContext": {
        "source": expected_source,
        "githubRepoContext": {"startingBranch": "main"}
    }
}

print("Creating Jules Session...")
resp = requests.post(
    f"{JULES_API}/sessions",
    headers={"X-Goog-Api-Key": jules_key, "Content-Type": "application/json"},
    json=payload
)
if not resp.ok:
    print(f"Jules Session Failed: {resp.text}")
    exit(1)

session = resp.json()
session_name = session["name"]
print(f"Session: {session_name}")

# Poll
print("Waiting for Jules...")
patch_content = None
for _ in range(360): # 1 hour
    time.sleep(10)
    status = requests.get(f"{JULES_API}/{session_name}", headers={"X-Goog-Api-Key": jules_key}).json()
    state = status.get("state")
    print(f"Status: {state}")
    if state == "COMPLETED":
        outputs = status.get("outputs", [])
        if outputs and "changeSet" in outputs[0]:
            patch_content = outputs[0]["changeSet"]["gitPatch"]["unidiffPatch"]
        break
    if state in ["FAILED", "ERROR"]:
        print(f"Jules Failed: {status}")
        exit(1)

if not patch_content:
    print("No patch returned!")
    exit(1)

print("Patch received!")
# Apply Patch
patch_file = TEST_DIR / "jules.patch"
with open(patch_file, "w", encoding="utf-8") as f:
    f.write(patch_content)

print("Applying Patch...")
# Use git apply
run("git apply --ignore-space-change --ignore-whitespace jules.patch", cwd=TEST_DIR)

# --- 4. Verify Build ---
print("\n--- Step 4: Verify Build ---")
print("Running npm run build...")
try:
    run("npm run build", cwd=TEST_DIR / "app")
    print("SUCCESS! App built with Jules changes.")
except subprocess.CalledProcessError:
    print("FAILURE! Build failed.")
    exit(1)
