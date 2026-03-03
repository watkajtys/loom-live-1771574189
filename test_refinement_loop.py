import os
import time
import requests
import subprocess
import shutil
from pathlib import Path
import google.generativeai as genai

# --- Configuration ---
TEST_DIR = Path(f"tmp_refine_{int(time.time())}")
JULES_API = "https://jules.googleapis.com/v1alpha"

# Load keys
keys = {}
if os.path.exists(".env"):
    with open(".env", "r") as f:
        for line in f:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                keys[k] = v

github_token = keys.get("GITHUB_TOKEN")
jules_key = keys.get("JULES_API_KEY")

gemini_key = "AIzaSyA5AFqr8E1z5DOmsy4a6tAXGnvT_GSZNNs"

if not github_token or not jules_key or not gemini_key:
    print("Error: Missing keys (GITHUB_TOKEN, JULES_API_KEY, GEMINI_API_KEY)")
    exit(1)

genai.configure(api_key=gemini_key)
overseer_model = genai.GenerativeModel('gemini-2.5-pro') # Using a capable model

def run(cmd, cwd=TEST_DIR):
    print(f"[{cwd}] > {cmd}")
    subprocess.run(cmd, cwd=cwd, shell=True, check=True)

# --- 1. Setup Test Environment & Seed Code ---
print("--- Step 1: Setting up Repository ---")
if TEST_DIR.exists():
    shutil.rmtree(TEST_DIR)
TEST_DIR.mkdir()

initial_code = """
export default function App() {
  return (
    <div className="p-4">
      <h1 className="text-xl">Dashboard</h1>
      <button className="bg-blue-500 text-white p-2 rounded">Click Me</button>
    </div>
  );
}
"""

with open(TEST_DIR / "App.tsx", "w") as f:
    f.write(initial_code)

run("git init")
run('git config user.email "test@example.com"')
run('git config user.name "Test User"')
run("git add .")
run('git commit -m "Initial commit with blue button"')

repo_name = f"loom-refine-{int(time.time())}"
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

run(f"git remote add origin {auth_url}")
run("git branch -M main")
run("git push -u origin main")

# --- 2. Overseer Critique ---
print("\\n--- Step 2: Overseer Critique ---")
overseer_prompt = f"""
You are the Overseer. Review the following React code. 
The requirement is that the button MUST be red, not blue. 
Provide a short, direct critique instructing the engineer to fix the color.

Code:
{initial_code}
"""
print("Asking Overseer for critique...")
response = overseer_model.generate_content(overseer_prompt)
critique = response.text.strip()
print(f"Overseer Critique: {critique}")

# --- 3. Jules Implementation (Fix) ---
print("\\n--- Step 3: Jules Refinement ---")
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

jules_prompt = f"""Update App.tsx based on the following critique from the Overseer:

{critique}"""

payload = {
    "prompt": jules_prompt,
    "sourceContext": {
        "source": expected_source,
        "githubRepoContext": {"startingBranch": "main"}
    }
}

print("Creating Jules Session for Refinement...")
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

print("Waiting for Jules...")
patch_content = None
for _ in range(1440): # 4 hour timeout
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

patch_file = TEST_DIR / "fix.patch"
with open(patch_file, "w", encoding="utf-8") as f:
    f.write(patch_content)

print("Applying Patch...")
run("git apply --ignore-space-change --ignore-whitespace fix.patch")

# --- 4. Verify ---
print("\\n--- Step 4: Verification ---")
with open(TEST_DIR / "App.tsx", "r") as f:
    final_code = f.read()

print("Final Code:")
print(final_code)

if "bg-red" in final_code and "bg-blue" not in final_code:
    print("SUCCESS! Jules applied the refinement correctly.")
else:
    print("FAILURE! Jules did not fix the code as requested.")
    exit(1)
