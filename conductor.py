import os
import sys
import time
import json
import logging
import subprocess
import signal
import psutil
import requests
from typing import List, Optional, Dict, Any
from pathlib import Path
from datetime import datetime
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.live import Live
from rich.layout import Layout
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables
load_dotenv()

# Setup Rich Console and Logging
console = Console()
logging.basicConfig(
    level="INFO",
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(console=console, rich_tracebacks=True)]
)
logger = logging.getLogger("loom")

# Constants
VITE_PORT = 5173
STATE_FILE = Path("session_state.json")
BROADCAST_FILE = Path("broadcast.jsonl")
DESIGN_DIR = Path("app/design")
SRC_DIR = Path("app/src")

# --- 1. State Management (The Brain) ---

class LoopIteration(BaseModel):
    id: int
    timestamp: str
    goal: str
    happiness_score: int = 0
    git_commit: Optional[str] = None
    critiques: List[str] = []

class ConductorState(BaseModel):
    project_name: str = "Loom Experiment"
    current_iteration: int = 0
    active_branch: str = "main"
    inspiration_goal: str = ""
    history: List[LoopIteration] = []
    
    def save(self):
        with open(STATE_FILE, "w") as f:
            f.write(self.model_dump_json(indent=2))
    
    @classmethod
    def load(cls) -> 'ConductorState':
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r") as f:
                    return cls.model_validate_json(f.read())
            except Exception as e:
                logger.error(f"Failed to load state: {e}. Starting fresh.")
        return cls()

# --- 2. Process Management (The Phoenix Server) ---

class PhoenixServer:
    """Manages the lifecycle of the Vite dev server."""
    
    def __init__(self, port: int = VITE_PORT):
        self.port = port
        self.process: Optional[subprocess.Popen] = None

    def kill(self):
        """Kills any process listening on the target port."""
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                for conn in proc.connections(kind='inet'):
                    if conn.laddr.port == self.port:
                        logger.warning(f"Killing zombie process {proc.name()} (PID: {proc.pid}) on port {self.port}")
                        proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

    def spawn(self):
        """Starts the Vite server in the background."""
        self.kill() # Ensure clean slate
        logger.info("Spawning Phoenix Server (Vite)...")
        try:
            # Using shell=True for Windows compatibility with npm
            self.process = subprocess.Popen(
                ["npm", "run", "dev"], 
                cwd="app",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True
            )
        except Exception as e:
            logger.error(f"Failed to spawn Vite: {e}")
            raise

    @retry(stop=stop_after_attempt(10), wait=wait_exponential(multiplier=1, min=2, max=10))
    def wait_for_ready(self):
        """Polls localhost until it returns 200 OK."""
        url = f"http://localhost:{self.port}"
        logger.info(f"Waiting for {url}...")
        response = requests.get(url, timeout=2)
        if response.status_code == 200:
            logger.info("Phoenix Server is READY.")
            return True
        raise Exception("Server not ready")

# --- 3. Agent Proxies (The Hands) ---

class AgentProxy:
    def _run(self, command: List[str], cwd: str = ".") -> str:
        logger.info(f"Running: {' '.join(command)}")
        try:
            result = subprocess.run(
                command, 
                cwd=cwd, 
                capture_output=True, 
                text=True, 
                check=True,
                timeout=300 # 5 minute timeout
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {e.stderr}")
            raise
        except subprocess.TimeoutExpired:
            logger.error("Command timed out!")
            raise

class GitClient(AgentProxy):
    def init(self):
        self._run(["git", "init"])
    
    def checkout_branch(self, branch_name: str):
        try:
            self._run(["git", "checkout", "-b", branch_name])
        except:
            self._run(["git", "checkout", branch_name])
            
    def commit(self, message: str):
        self._run(["git", "add", "."])
        try:
            self._run(["git", "commit", "-m", message])
            return self._run(["git", "rev-parse", "HEAD"])
        except:
            logger.warning("Nothing to commit.")
            return None

class GeminiCoderClient(AgentProxy):
    """
    Simulates the Jules Agent using Gemini Pro.
    Reads the Stitch HTML and the App File Structure, then generates React Code.
    """
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.warning("GEMINI_API_KEY missing for Coder. Code generation will fail.")
        else:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-pro')

    def run_task(self, prompt: str, design_path: str = None):
        logger.info(f"Tasking Gemini Coder: {prompt}")
        
        # 1. Gather Context
        context = ""
        if design_path and os.path.exists(design_path):
            with open(design_path, "r") as f:
                context += f"\n--- STITCH DESIGN HTML ---\n{f.read()}\n"
        
        # Read key app files for context (simplified)
        for fpath in ["app/src/App.tsx", "app/tailwind.config.js"]:
            if os.path.exists(fpath):
                with open(fpath, "r") as f:
                    context += f"\n--- {fpath} ---\n{f.read()}\n"

        # 2. Construct Prompt
        full_prompt = f"""
        You are an expert React Engineer. Your task is to implement a UI based on the provided Design HTML.
        
        System Constraints:
        - Use React + Vite + Tailwind CSS.
        - The project is in 'app/'.
        - MODIFY 'app/src/App.tsx' to render the new design.
        - You may create new components if needed, but for now, monolithic App.tsx is fine for prototyping.
        - Ensure all imports are correct.
        
        Task: {prompt}
        
        Context:
        {context}
        
        Output:
        Return a JSON object with the file updates.
        Example:
        {{
          "app/src/App.tsx": "import ...",
          "app/src/components/Button.tsx": "..."
        }}
        """
        
        # 3. Call LLM
        try:
            response = self.model.generate_content(full_prompt)
            text = response.text
            
            # 4. Parse JSON (Naive regex or cleaning)
            # Remove markdown code blocks if present
            clean_text = text.replace("```json", "").replace("```", "").strip()
            files_to_write = json.loads(clean_text)
            
            # 5. Apply Changes
            for fpath, content in files_to_write.items():
                logger.info(f"Writing file: {fpath}")
                # Ensure directory exists
                os.makedirs(os.path.dirname(fpath), exist_ok=True)
                with open(fpath, "w") as f:
                    f.write(content)
            
            return "Code Implemented"
            
        except Exception as e:
            logger.error(f"Gemini Coding Failed: {e}")
            raise

class StitchClient(AgentProxy):
    """
    Direct client for the Stitch MCP HTTP API.
    Uses 'gcloud auth print-access-token' for authentication.
    """
    BASE_URL = "https://stitch.googleapis.com/mcp"

    def _get_access_token(self) -> str:
        try:
            # Check for env var first (for CI/CD or non-gcloud envs)
            token = os.getenv("STITCH_ACCESS_TOKEN")
            if token:
                return token
            # Fallback to gcloud
            return self._run(["gcloud", "auth", "print-access-token"]).strip()
        except Exception as e:
            logger.error(f"Failed to get gcloud token: {e}")
            raise

    def generate_screen(self, description: str) -> str:
        logger.info(f"Tasking Stitch API: {description}")
        
        try:
            # 1. Determine Auth Method
            api_key = os.getenv("STITCH_API_KEY")
            project_id = os.getenv("STITCH_PROJECT_ID")
            access_token = None
            
            if not project_id:
                raise ValueError("STITCH_PROJECT_ID not found in environment.")

            headers = {
                "Content-Type": "application/json",
            }

            if api_key:
                logger.info("Using Stitch API Key for authentication.")
                headers["X-Goog-Api-Key"] = api_key
            else:
                logger.info("Using Google Cloud OAuth for authentication.")
                access_token = self._get_access_token()
                headers["Authorization"] = f"Bearer {access_token}"
                headers["X-Goog-User-Project"] = project_id

            # MCP Tool Call Payload
            payload = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "create_screen",
                    "arguments": {
                        "projectId": project_id,
                        "description": description
                    }
                },
                "id": 1
            }
            
            # Call Stitch
            logger.info("Calling Stitch API (timeout=120s)...")
            response = requests.post(self.BASE_URL, json=payload, headers=headers, timeout=120)
            
            if not response.ok:
                logger.error(f"Stitch API Error ({response.status_code}): {response.text}")
                raise Exception(f"Stitch API request failed: {response.status_code}")

            data = response.json()
            if "error" in data:
                 raise Exception(f"Stitch API Error: {data['error']}")
            
            # Extract HTML (Defensive Coding)
            result = data.get("result", {})
            content_blocks = result.get("content", [])
            html_content = ""
            
            for block in content_blocks:
                if block.get("type") == "text":
                    raw_text = block.get("text", "")
                    try:
                        inner_json = json.loads(raw_text)
                        # Navigate to the first screen's HTML code
                        screens = inner_json.get("outputComponents", [{}])[0].get("design", {}).get("screens", [])
                        if screens and "htmlCode" in screens[0]:
                            download_url = screens[0]["htmlCode"].get("downloadUrl")
                            if download_url:
                                logger.info(f"Downloading HTML from: {download_url}")
                                html_resp = requests.get(download_url, timeout=30)
                                if html_resp.ok:
                                    html_content = html_resp.text
                    except json.JSONDecodeError:
                        logger.warning("Could not parse inner JSON from Stitch response.")

            if not html_content:
                logger.warning("Stitch returned no HTML content. Using fallback.")
                html_content = f"<!-- Stitch Design for: {description} -->\n<div class='min-h-screen bg-slate-900 text-white flex items-center justify-center'>\n  <div class='p-8 bg-slate-800 rounded-xl shadow-2xl border border-slate-700'>\n    <h1 class='text-4xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-purple-500 mb-4'>Stitch Loom</h1>\n    <p class='text-slate-400 mb-6'>Design generated for: {description}</p>\n    <div class='mt-4 p-4 bg-slate-900/50 rounded-lg text-xs font-mono text-slate-500'>Target Project: {project_id}</div>\n    <button class='mt-6 px-6 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg font-medium transition-all'>Initialize System</button>\n  </div>\n</div>"

            # Save to file
            design_file = DESIGN_DIR / "latest_design.html"
            DESIGN_DIR.mkdir(parents=True, exist_ok=True)
            with open(design_file, "w") as f:
                f.write(html_content)
                
            return str(design_file)
            
        except Exception as e:
            logger.error(f"Stitch Generation Failed: {e}. Using fallback.")
            design_file = DESIGN_DIR / "latest_design.html"
            DESIGN_DIR.mkdir(parents=True, exist_ok=True)
            if not design_file.exists():
                with open(design_file, "w") as f:
                    f.write(f"<!-- Fallback Design for: {description} -->\n<div class='p-10 bg-red-100 text-red-800'><h1>Stitch Connection Failed</h1><p>{e}</p></div>")
            return str(design_file)

# --- 4. The Overseer (Executive Logic) ---

class Overseer:
    def __init__(self):
        self.state = ConductorState.load()
        self.git = GitClient()
        self.jules = GeminiCoderClient() # Renamed to simulate Jules
        self.stitch = StitchClient()
        self.phoenix = PhoenixServer()
        
        # Initialize Gemini
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.warning("GEMINI_API_KEY not found. Overseer will be lobotomized.")
        else:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-pro')
            self.vision_model = genai.GenerativeModel('gemini-pro-vision')

    def think(self, context: str) -> str:
        """Consults the LLM for the next move."""
        if not hasattr(self, 'model'): return "Mock thought: Proceed."
        response = self.model.generate_content(f"You are the Overseer of an autonomous coding loop. Context: {context}. What is the next logical step?")
        return response.text

    def evaluate_happiness(self) -> int:
        """
        The 'Happiness' Logic.
        1. Check if server is running (Phoenix).
        2. Check for console errors (Runtime).
        3. Visual check (Vision).
        """
        score = 10 # Start optimistic
        
        try:
            self.phoenix.spawn()
            self.phoenix.wait_for_ready()
            
            # TODO: Implement actual Screenshot + Vision API call here
            # For V1, we simulate a random critique if we can't see
            logger.info("Phoenix Server is up. App is running.")
            
            # Check for build errors in console logs (not implemented in V1 mock)
            
        except Exception as e:
            logger.error(f"Happiness Check Failed: {e}")
            score = 0
        finally:
            self.phoenix.kill()
            
        return score

    def loop(self):
        logger.info("[bold green]Starting Loom Loop...[/bold green]", extra={"markup": True})
        
        while True:
            # 1. Inspiration
            if not self.state.inspiration_goal:
                self.state.inspiration_goal = "Create a simple Pomodoro timer with a cyberpunk aesthetic."
                logger.info(f"New Goal: {self.state.inspiration_goal}")

            # 2. Iteration Setup
            self.state.current_iteration += 1
            branch_name = f"iter-{self.state.current_iteration}"
            self.git.checkout_branch(branch_name)
            
            # 3. Design (Stitch)
            self.stitch.generate_screen(self.state.inspiration_goal)
            
            # 4. Build (Jules)
            task_prompt = f"Implement the design for '{self.state.inspiration_goal}' using React, Vite, and Tailwind. The design files are in app/design. Use strict TypeScript."
            try:
                self.jules.run_task(task_prompt)
                self.git.commit(f"feat: implementation for iter {self.state.current_iteration}")
            except Exception as e:
                logger.error(f"Build failed: {e}")
            
            # 5. Evaluate
            happiness = self.evaluate_happiness()
            logger.info(f"Happiness Score: {happiness}/10")
            
            # 6. Save State
            iteration_record = LoopIteration(
                id=self.state.current_iteration,
                timestamp=str(datetime.now()),
                goal=self.state.inspiration_goal,
                happiness_score=happiness
            )
            self.state.history.append(iteration_record)
            self.state.save()
            
            # 7. Decision
            if happiness >= 8:
                logger.info("Happiness achieved! Merging to main.")
                self.git.checkout_branch("main")
                self.git._run(["git", "merge", branch_name])
                
                # Meta Loop: Brainstorm the next addition
                logger.info("Brainstorming next addition to keep the build going...")
                next_idea = self.think(f"We just successfully implemented: '{self.state.inspiration_goal}'. Generate a short, single sentence idea for the next small feature, visual improvement, or iteration to add to this app. Be creative but keep it simple.")
                logger.info(f"Next Idea: {next_idea.strip()}")
                self.state.inspiration_goal = next_idea.strip()
            else:
                logger.info("Unhappy. Retrying in next iteration...")
            
            # Pause to prevent API spam in this loop
            logger.info("Waiting 10 seconds before next loop...")
            time.sleep(10)

if __name__ == "__main__":
    conductor = Overseer()
    try:
        conductor.loop()
    except KeyboardInterrupt:
        logger.info("Loom stopped by user.")
        conductor.phoenix.kill()
