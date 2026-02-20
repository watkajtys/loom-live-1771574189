import os
import time
import requests
import logging
from typing import Optional
from loom.agents.base import AgentProxy

logger = logging.getLogger("loom")

class GitClient(AgentProxy):
    def init(self):
        self._run(["git", "init"], cwd="app")
    
    def checkout_branch(self, branch_name: str):
        try:
            self._run(["git", "checkout", "-b", branch_name], cwd="app")
        except:
            self._run(["git", "checkout", branch_name], cwd="app")
            
    def commit(self, message: str) -> Optional[str]:
        self._run(["git", "add", "."], cwd="app")
        try:
            self._run(["git", "commit", "-m", message], cwd="app")
            return self._run(["git", "rev-parse", "HEAD"], cwd="app")
        except:
            logger.warning("Nothing to commit.")
            return None
            
    def push_branch(self, branch_name: str):
        try:
            self._run(["git", "push", "-u", "origin", branch_name], cwd="app")
        except Exception as e:
            logger.error(f"Failed to push branch: {e}")
            raise
            
    def get_remote_url(self) -> str:
        return self._run(["git", "config", "--get", "remote.origin.url"], cwd="app")

    def ensure_remote(self):
        # ... rest of the method ...
        try:
            url = self.get_remote_url()
            if url:
                logger.info(f"Remote origin already exists: {url}")
                return
        except:
            pass # No remote origin

        logger.info("No remote origin found. Creating a new GitHub repository...")
        github_token = os.getenv("GITHUB_TOKEN")
        if not github_token:
            raise Exception("GITHUB_TOKEN missing. Cannot create remote repository.")
        
        repo_name = f"loom-live-{int(time.time())}"
        resp = requests.post(
            "https://api.github.com/user/repos",
            headers={"Authorization": f"token {github_token}"},
            json={"name": repo_name, "private": False}
        )
        if not resp.ok:
            raise Exception(f"GitHub Error creating repo: {resp.text}")
            
        repo_data = resp.json()
        clone_url = repo_data["clone_url"]
        auth_url = clone_url.replace("https://", f"https://{github_token}@")
        
        self.init() # Ensure git is initialized in app/
        self._run(["git", "remote", "add", "origin", auth_url], cwd="app")
        self._run(["git", "branch", "-M", "main"], cwd="app")
        # Ensure initial commit exists
        self.commit("Initial commit for Project Loom")
        self.push_branch("main")
        logger.info(f"Created and pushed to new remote repository: {clone_url}")
