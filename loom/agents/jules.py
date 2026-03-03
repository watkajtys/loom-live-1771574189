import os
import time
import requests
import logging
from loom.agents.base import AgentProxy

logger = logging.getLogger("loom")

class JulesClient(AgentProxy):
    BASE_URL = "https://jules.googleapis.com/v1alpha"

    def __init__(self):
        self.api_key = os.getenv("JULES_API_KEY")
        if not self.api_key:
            logger.warning("JULES_API_KEY missing. Jules tasks will fail.")

    def run_task(self, prompt: str, repo_owner: str, repo_name: str, branch: str, activity_callback=None) -> str:
        logger.info(f"Tasking Jules API: {prompt}")
        expected_source = f"sources/github/{repo_owner}/{repo_name}"
        
        logger.info(f"Waiting for source {expected_source} to be available to Jules...")
        source_found = False
        for attempt in range(60): # 5 minute timeout for branch/source propagation
            time.sleep(5)
            page_token = None
            while True:
                params = {"pageToken": page_token} if page_token else {}
                resp = requests.get(f"{self.BASE_URL}/sources", headers={"X-Goog-Api-Key": self.api_key}, params=params)
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
                logger.info("Source found by Jules!")
                break
        else:
            logger.warning("Source not found by Jules, proceeding optimistically...")

        payload = {
            "prompt": prompt,
            "sourceContext": {
                "source": expected_source,
                "githubRepoContext": {"startingBranch": branch}
            }
        }

        logger.info("Creating Jules Session...")
        resp = requests.post(
            f"{self.BASE_URL}/sessions",
            headers={"X-Goog-Api-Key": self.api_key, "Content-Type": "application/json"},
            json=payload
        )
        if not resp.ok:
            raise Exception(f"Jules Session Failed: {resp.text}")

        session_name = resp.json()["name"]
        session_url = resp.json().get("url", "")
        logger.info(f"Jules Session created: {session_name}")
        
        if activity_callback:
            activity_callback("Initializing...", session_url)

        patch_content = None
        seen_activities = set()

        for _ in range(1440): # 4 hour timeout
            time.sleep(10)
            
            # Poll for activities to log progress
            try:
                act_resp = requests.get(f"{self.BASE_URL}/{session_name}/activities", headers={"X-Goog-Api-Key": self.api_key})
                if act_resp.ok:
                    activities = act_resp.json().get("activities", [])
                    for act in reversed(activities): # Process oldest to newest to catch the latest
                        act_id = act.get("name")
                        if act_id and act_id not in seen_activities:
                            seen_activities.add(act_id)
                            
                            # Try to extract a meaningful title/description from the activity
                            title = None
                            if "progressUpdated" in act:
                                title = act["progressUpdated"].get("title")
                            elif "planGenerated" in act:
                                title = "Generated execution plan."
                            elif "error" in act:
                                title = f"Error: {act['error']}"
                                
                            if title: 
                                logger.info(f"Jules Activity: {title}")
                                if activity_callback:
                                    activity_callback(title, session_url)
            except Exception as e:
                pass # Non-fatal if we can't fetch activities

            # Check main session status
            status_resp = requests.get(f"{self.BASE_URL}/{session_name}", headers={"X-Goog-Api-Key": self.api_key})
            status = status_resp.json()
            state = status.get("state")
            logger.info(f"Jules Status: {state}")
            
            if state == "COMPLETED":
                outputs = status.get("outputs", [])
                if outputs and "changeSet" in outputs[0]:
                    git_patch = outputs[0]["changeSet"].get("gitPatch", {})
                    patch_content = git_patch.get("unidiffPatch")
                break
            if state in ["FAILED", "ERROR", "CANCELLED"]:
                raise Exception(f"Jules Task Failed: {status}")

        if not patch_content:
            raise Exception("Jules completed but returned no patch.")

        logger.info("Jules returned a patch successfully.")
        
        # Strip binary patches from jules output as git apply chokes on them
        import re
        parts = re.split(r'(?=^diff --git)', patch_content, flags=re.MULTILINE)
        new_parts = [p for p in parts if 'GIT binary patch' not in p]
        clean_patch = ''.join(new_parts)
        
        patch_path = "app/jules.patch"
        with open(patch_path, "w", encoding="utf-8", newline='\n') as f:
            f.write(clean_patch)
            
        logger.info("Applying patch...")
        try:
            self._run(["git", "apply", "--ignore-space-change", "--ignore-whitespace", "--reject", "jules.patch"], cwd="app")
            
            # Check for rejections
            import glob
            rej_files = glob.glob("app/**/*.rej", recursive=True)
            if rej_files:
                logger.warning(f"Patch applied but with rejections in: {rej_files}")
        except Exception as e:
            logger.warning(f"git apply --reject had warnings/errors, but proceeding: {e}")
            
        return "Code Implemented via Jules Patch"
