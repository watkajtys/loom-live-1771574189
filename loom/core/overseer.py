import os
import shutil
import time
import logging
import subprocess
import concurrent.futures
import re
import json
import random
from enum import Enum
from datetime import datetime
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv

from loom.core.state import ConductorState, LoopIteration, AttemptRecord
from loom.environment.git import GitClient
from loom.environment.phoenix import PhoenixServer
from loom.agents.stitch import StitchClient
from loom.agents.jules import JulesClient
from loom.agents.mock_jules import MockJulesClient

load_dotenv(override=True)

logger = logging.getLogger("loom")

class LoomPhase(Enum):
    INSPIRATION = "Inspiration"
    DESIGN = "Design"
    IMPLEMENTATION = "Implementation"
    VALIDATION = "Validation"
    REFLECTION = "Reflection"
    DECISION = "Decision"

logger = logging.getLogger("loom")

class Overseer:
    def __init__(self):
        self.state = ConductorState.load()
        self.git = GitClient()
        
        # Use service name for PocketBase inside Docker
        self.pb_url = "http://pocketbase:8090"
        
        # Use Mock Jules if requested
        if os.getenv("USE_MOCK_JULES", "").lower() == "true":
            logger.info("[bold yellow]Using Mock Jules Client (Local Gemini)[/bold yellow]", extra={"markup": True})
            self.jules = MockJulesClient()
        else:
            self.jules = JulesClient()
            
        self.stitch = StitchClient()
        self.phoenix = PhoenixServer()
        
        # Iteration-specific state
        self.current_iteration_record = None
        self.current_brainstorm_output = None
        self.happiness_score = 0
        self.last_critique = ""
        self.app_screenshot = None
        self.app_screenshot_path = None
        self.patch_dest_rel = None
        
        # Long-term memory
        self.lab_memory = {}
        memory_path = Path("loom_memory.json")
        if memory_path.exists() and memory_path.is_dir():
            shutil.rmtree(memory_path)
            
        if memory_path.exists():
            try:
                with open(memory_path, "r", encoding="utf-8") as f:
                    self.lab_memory = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load loom_memory.json: {e}")
        else:
            with open(memory_path, "w", encoding="utf-8") as f:
                json.dump({"archive_count": 0, "technical_learnings": [], "past_projects": []}, f)
        
        # Ensure artifacts directory exists
        os.makedirs("viewer/public/artifacts", exist_ok=True)
        
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.warning("GEMINI_API_KEY not found. Overseer will be lobotomized.")
        else:
            genai.configure(api_key=api_key)
            # Principal Overseer (Logic & Planning)
            self.model = genai.GenerativeModel('gemini-3.1-pro-preview')
            # Specialized Reviewers (Fast & Efficient)
            self.arch_model = genai.GenerativeModel('gemini-3-flash-preview')
            self.vision_model = genai.GenerativeModel('gemini-3-flash-preview')

    def think(self, context: str, image_data: bytes = None, temperature: float = 0.7) -> str:
        """Consults the LLM for the next move with a hidden nonce to avoid caching."""
        if not hasattr(self, 'model'): return "Mock thought: Proceed."
        
        import uuid
        nonce = uuid.uuid4().hex[:8]
        prompt = f"You are the Overseer of Project Loom. We're building software together. [Request ID: {nonce}] Context: {context}"
        generation_config = genai.types.GenerationConfig(temperature=temperature)
        
        if image_data:
            content = [prompt, {"mime_type": "image/png", "data": image_data}]
            response = self.model.generate_content(content, generation_config=generation_config)
        else:
            response = self.model.generate_content(prompt, generation_config=generation_config)
        return response.text

    def _take_screenshot(self, url_or_path: str, wait_ms: int = 5000, return_logs: bool = False):
        from playwright.sync_api import sync_playwright
        logs = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            # Set standard desktop viewport
            context = browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = context.new_page()
            
            if return_logs:
                page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text}"))
                page.on("pageerror", lambda exc: logs.append(f"[uncaught error] {exc}"))

            if url_or_path.startswith("http"):
                page.goto(url_or_path)
            else:
                # Handle Windows paths for file:// URIs
                clean_path = url_or_path.replace('\\', '/')
                page.goto(f"file:///{clean_path}")
            page.wait_for_timeout(wait_ms)
            screenshot = page.screenshot()
            browser.close()
            
            if return_logs:
                return screenshot, logs
            return screenshot

    def evaluate_architecture(self, branch_name: str) -> tuple[int, str]:
        logger.info("Evaluating full codebase architecture...")
        try:
            source_code = ""
            for root, _, files in os.walk("app/src"):
                for file in files:
                    if file.endswith(('.tsx', '.ts', '.jsx', '.js', '.css')):
                        file_path = os.path.join(root, file)
                        try:
                            with open(file_path, "r", encoding="utf-8") as f:
                                rel_path = os.path.relpath(file_path, "app")
                                source_code += f"\n--- {rel_path} ---\n```\n{f.read()}\n```\n"
                        except Exception:
                            pass
            
            try:
                with open("app/package.json", "r", encoding="utf-8") as f:
                    source_code += f"\n--- package.json ---\n```json\n{f.read()}\n```\n"
            except:
                pass
                
            prompt = f"""
You are an expert Principal Software Engineer acting as the Architectural Reviewer for Project Loom.
The application is built using React, Vite, and Tailwind CSS.
App Identity & Core Architecture: {self.state.app_meta}

Please review the entire current codebase provided below.

Evaluate the codebase based on:
1. Technical best practices (React hooks, state management, pure functions).
2. Modularity and separation of concerns (are components getting too large? Should they be split?).
3. Maintainability, readability, and file structure.
4. Alignment with the App Identity/Architecture defined above.
5. Any potential performance bottlenecks (unnecessary re-renders, complex layout thrashing).

Provide a concise, highly technical architectural critique (under 250 words). Focus strictly on the code quality and structure, not the visual design.
Finally, give the architecture a score from 1 to 10. Output ONLY the integer score on the very last line of your response.

FULL CODEBASE:
{source_code}
"""
            review_response = self.arch_model.generate_content(prompt)
            review_text = review_response.text.strip()
            logger.info(f"Architectural Critique:\n{review_text}")
            
            lines = [l.strip() for l in review_text.split('\n') if l.strip()]
            score_str = ''.join(filter(str.isdigit, lines[-1]))
            score = int(score_str) if score_str else 5
            score = max(1, min(10, score))
            
            return score, review_text
            
        except Exception as e:
            logger.error(f"Failed to evaluate architecture: {e}")
            return 5, f"Architectural evaluation failed: {str(e)}"

    def evaluate_happiness(self, target_route: str = "/") -> tuple[int, str, bytes]:
        score = 10 
        critique = "No critique."
        app_screenshot = None
        try:
            self.phoenix.spawn()
            self.phoenix.wait_for_ready()
            logger.info(f"Phoenix Server is up. App is running. Verifying route {target_route} with Vision...")
            
            try:
                # 1. Capture Live App
                if self.app_screenshot_path and os.path.exists(f"viewer/public/{self.app_screenshot_path}"):
                    logger.info(f"Using Playwright evidence screenshot: {self.app_screenshot_path}")
                    with open(f"viewer/public/{self.app_screenshot_path}", "rb") as f:
                        app_screenshot = f.read()
                    console_logs = [] 
                else:
                    app_screenshot, console_logs = self._take_screenshot(f"http://localhost:{self.phoenix.port}{target_route}", return_logs=True)
                
                # 2. Collect ALL reference images for this iteration
                ref_images = []
                # Always include the primary reference.png if it exists
                ref_primary = os.path.abspath("app/design/reference.png")
                if os.path.exists(ref_primary):
                    with open(ref_primary, "rb") as f:
                        ref_images.append(f.read())
                
                # Look for other images in the artifacts directory for this iteration
                artifact_dir = "viewer/public/artifacts"
                if os.path.exists(artifact_dir):
                    iter_prefix = f"iter_{self.state.current_iteration}_"
                    for f_name in os.listdir(artifact_dir):
                        if f_name.startswith(iter_prefix) and f_name.endswith(".png"):
                            # Filter for images that were part of the chosen design path
                            if "evolved" in f_name or "seed" in f_name or "theme" in f_name:
                                with open(os.path.join(artifact_dir, f_name), "rb") as f:
                                    ref_images.append(f.read())

                if hasattr(self, 'model'):
                    prompt = [
                        f"You are the Overseer. Your goal was to implement: '{self.state.inspiration_goal}'.\n",
                        f"App Identity (Meta): {self.state.app_meta}\n",
                        f"Target Route: {target_route}\n",
                        "The first image is the actual React app running."
                    ]
                    content = [{"mime_type": "image/png", "data": app_screenshot}]
                    
                    if ref_images:
                        prompt.append(f"The following {len(ref_images)} images are the target design references we are trying to achieve (Desktop, Mobile, or variants).")
                        for img_bytes in ref_images[:5]: # Limit to 5 images to avoid token blowup
                            content.append({"mime_type": "image/png", "data": img_bytes})
                        
                    prompt.append("Score how well the actual app matches the target design and the core App Identity from 0 to 10. Pay special attention to whether the new feature was integrated correctly without destroying existing UI. Output ONLY the integer score on the first line, followed by a brief critique on the next lines.")
                    
                    if console_logs:
                        logs_str = "\n".join(console_logs[:20]) # Limit to 20 lines
                        prompt.append(f"\nCRITICAL: The browser console reported the following logs/errors. Factor these heavily into your score and critique:\n{logs_str}")

                    response = self.vision_model.generate_content([*prompt, *content])
                    critique = response.text.strip()
                    logger.info(f"Vision Critique:\n{critique}")
                    
                    try:
                        score_str = critique.split("\n")[0].strip()
                        score = int(''.join(filter(str.isdigit, score_str)))
                        score = max(0, min(10, score))
                    except Exception as e:
                        logger.warning(f"Failed to parse score from Vision: {e}")
                        score = 5
            except Exception as e:
                logger.error(f"Vision verification failed: {e}")
                score = 5
                critique = f"Vision failed: {e}"

        except Exception as e:
            logger.error(f"Happiness Check Failed: {e}")
            score = 0
            critique = f"Server failed to boot: {e}"
        finally:
            self.phoenix.kill()
        return score, critique, app_screenshot

    def _get_repo_info(self):
        url = self.git.get_remote_url()
        parts = url.split("/")
        repo = parts[-1].replace(".git", "")
        owner = parts[-2]
        return owner, repo

    def _update_env_file(self, key: str, value: str):
        """Updates a specific key in the .env file."""
        env_path = ".env"
        if not os.path.exists(env_path):
            with open(env_path, "w") as f:
                f.write(f"{key}={value}\n")
            return

        with open(env_path, "r") as f:
            lines = f.readlines()

        found = False
        new_lines = []
        for line in lines:
            if line.startswith(f"{key}="):
                new_lines.append(f"{key}={value}\n")
                found = True
            else:
                new_lines.append(line)

        if not found:
            new_lines.append(f"{key}={value}\n")

        with open(env_path, "w") as f:
            f.writelines(new_lines)
        logger.info(f"Updated {env_path} with {key}={value}")

    def ensure_scaffold(self):
        """Ensures that a basic React + Vite + Tailwind project exists in the app/ directory."""
        if os.path.exists("app/src"):
            return

        logger.info("[bold yellow]No React project detected. Scaffolding initial application...[/bold yellow]", extra={"markup": True})
        
        # 1. Package.json
        package_json = {
            "name": "app",
            "private": True,
            "version": "0.0.0",
            "type": "module",
            "scripts": {
                "dev": "vite --host",
                "build": "vite build",
                "lint": "eslint .",
                "preview": "vite preview",
                "test:e2e": "playwright test"
            },
            "dependencies": {
                "react": "^19.0.0",
                "react-dom": "^19.0.0",
                "react-router-dom": "^7.0.0",
                "lucide-react": "^0.454.0",
                "pocketbase": "^0.21.1"
            },
            "devDependencies": {
                "@playwright/test": "^1.42.0",
                "@types/node": "^20.11.24",
                "@vitejs/plugin-react": "^4.3.0",
                "autoprefixer": "^10.4.19",
                "postcss": "^8.4.38",
                "tailwindcss": "^3.4.3",
                "typescript": "^5.2.2",
                "vite": "^6.0.0"
            }
        }
        
        os.makedirs("app/src", exist_ok=True)
        os.makedirs("app/public", exist_ok=True)
        
        import json
        with open("app/package.json", "w") as f:
            json.dump(package_json, f, indent=2)
            
        # 2. Vite Config
        with open("app/vite.config.ts", "w") as f:
            f.write("""import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
})
""")

        # 3. Tailwind Config
        with open("app/tailwind.config.js", "w") as f:
            f.write("""/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
""")

        # 4. PostCSS Config
        with open("app/postcss.config.js", "w") as f:
            f.write("""export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
""")

        # 5. Index.html
        with open("app/index.html", "w") as f:
            f.write("""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Loom App</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
""")

        # 5.5 Playwright Config
        with open("app/playwright.config.ts", "w") as f:
            f.write("""import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
""")
        os.makedirs("app/tests", exist_ok=True)
        with open("app/tests/verify.spec.ts", "w") as f:
            f.write("""import { test, expect } from '@playwright/test';

test('App initializes correctly', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('text=Loom Initialized')).toBeVisible();
});
""")

        # 6. Basic SRC files
        with open("app/src/index.css", "w") as f:
            f.write("@tailwind base;\n@tailwind components;\n@tailwind utilities;\n")
            
        with open("app/src/App.tsx", "w") as f:
            f.write("""export default function App() {
  return (
    <div className="min-h-screen bg-slate-950 text-white flex items-center justify-center">
      <h1 className="text-4xl font-bold">Loom Initialized</h1>
    </div>
  )
}
""")

        with open("app/src/main.tsx", "w") as f:
            f.write("""import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
""")

        # 7. Git Init & Commit
        try:
            self.git._run(["git", "init"], cwd="app")
            self.git._run(["git", "add", "."], cwd="app")
            self.git.commit("chore: initial scaffold")
            logger.info("[bold green]Scaffolding complete.[/bold green]", extra={"markup": True})
        except Exception as e:
            logger.warning(f"Failed to commit scaffold: {e}")

    def loop(self):
        logger.info("[bold green]Starting Loom Loop...[/bold green]", extra={"markup": True})
        self.git.ensure_remote()
        self.ensure_scaffold()
        
        # Resume state if history exists
        if self.state.history:
            self.state.inspiration_target_route = self.state.history[-1].target_route
            self.state.inspiration_requires_design = self.state.history[-1].requires_design
        
        while True:
            try:
                # _step_inspiration now handles full iteration setup (incrementing, branch, record)
                branch_name = self._step_inspiration()

                try:
                    self._step_design()
                    self._step_implementation(branch_name)
                    self._step_reflection()
                except Exception as step_error:
                    logger.error(f"Iteration aborted due to step error: {step_error}")
                    self.happiness_score = 0
                    self.last_critique = f"Aborted during phase {self.state.current_phase}: {step_error}"

                self._step_decision(branch_name)
                
                time.sleep(10)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                logger.error(f"Critical loop error: {e}")
                time.sleep(30)

    def _step_inspiration(self) -> str:
        self.state.current_phase = LoomPhase.INSPIRATION.value
        if not self.state.inspiration_goal:
            if not self.state.app_meta:
                self.state.current_status = "Scanning market gaps for new Micro-SaaS opportunities..."
                self.state.save()
                logger.info("Overseer is conducting a Micro-SaaS product discovery pass...")
                
                import random
                entropy_seed = random.getrandbits(64)

                past_history = ""
                if self.state.history:
                    past_history = "\n### LAB ARCHIVE (PREVIOUS PROTOTYPES)\nDo not repeat these specific product niches:\n"
                    for h in self.state.history[-10:]:
                        past_history += f"- {h.goal[:100]}...\n"
                
                # Inject long-term memory projects if they exist
                if self.lab_memory.get("past_projects"):
                    if not past_history:
                        past_history = "\n### LAB ARCHIVE (PREVIOUS PROTOTYPES)\nDo not repeat these specific product niches:\n"
                    for p in self.lab_memory["past_projects"]:
                        past_history += f"- {p.get('name')}: {p.get('niche')}\n"

                memory_context = ""
                if self.state.repo_memory.get("learnings"):
                    memory_context = "\n### LAB TECHNICAL NOTES\n"
                    for l in self.state.repo_memory["learnings"][-3:]:
                        status = "Success" if l['success'] else "Failure"
                        memory_context += f"- Iteration {l['iteration']} ({status}): {l['takeaways']}\n"
                
                prompt = f"""
You are a Lead Product Designer at an Indie Creative Tools Lab. 
Your goal is to build a "Beautifully Simple Video Review Studio" designed specifically for independent creators and small teams who find current professional tools too bloated.

[Studio Entropy Seed: {entropy_seed}]
{past_history}

CRITICAL DIRECTIVES:
1. **TIMELINE-FIRST FEEDBACK:** The core of the product is the timeline. It must be "Super Easy" to scrub through a video and leave a comment at a precise timestamp.
2. **INDIE-FOCUSED UTILITY:** Focus on frictionless features: one-click video uploads, simple threaded comments on the timeline, and an interface that feels fast and lightweight.
3. **FUNCTIONAL SIMPLICITY:** Move beyond complex "node graphs" or "S3 pipelines." Focus on the *User Experience* of a person saying "Fix this at 00:42."
4. **AVOID WEIRDNESS:** Do not try to be "disruptive" or "revolutionary." Just build the most functional, reliable, and "obvious" version of a video review tool. 

### YOUR TASK:
1. Brainstorm 5 distinct "Indie Video Studio" concepts. 
   - Each should explore a different "Simplicity Edge" (e.g., one focused on mobile review, one on ultra-fast feedback, one on social-media-first creators).
2. For each idea, define the "Timeline Interaction" (how the user leaves feedback) and the "Sharing Flow."
3. Select the concept that is the most "Utility-First" and "Indie-Friendly."

CRITICAL: DO NOT describe colors or fonts. Define THE PRODUCT and ITS ARCHITECTURE.

4. Output your choice using the following structured tags:

[SELECTED CONCEPT]
A detailed paragraph describing the app's architecture, core timeline features, and the primary user flow.

[APP_META]
Name: [A friendly, 1-2 word name for the product]
Palette: [A sensory description of the colors]
Typography: [The vibe of the font]

[DATA_MODEL]
Define the PocketBase schema (collections, fields) required for projects, video files, and timeline comments.

[TARGET_ROUTE]
The URL path where the core experience will live (e.g. /review, /project, /watch)

[REQUIRES_DESIGN]
TRUE, FALSE, or REFINEMENT

[TEST_SCENARIO]
A step-by-step description of a specific interaction (e.g., "The user drags the playhead to 10 seconds, clicks the timeline, types 'Great shot', and verifies the comment appears at that exact spot").
"""
                raw_response = self.think(prompt, temperature=0.9)
                logger.info(f"Studio Brainstorming Output:\n{raw_response}")
                self.current_brainstorm_output = raw_response            
                if "[SELECTED CONCEPT]" in raw_response:
                    self.state.inspiration_goal = raw_response.split("[SELECTED CONCEPT]")[1].split("[")[0].strip().lstrip(",: ").strip()
                else:
                    self.state.inspiration_goal = raw_response.strip().split("\n")[-1].lstrip(",: ").strip()

                if "[APP_META]" in raw_response:
                    meta_part = raw_response.split("[APP_META]")[1]
                    self.state.app_meta = (meta_part.split("[")[0].strip() if "[" in meta_part else meta_part.strip()).lstrip(",: ").strip()
                    # Ensure app directory exists before writing meta
                    os.makedirs("app", exist_ok=True)
                    with open("app/APP_META.md", "w", encoding="utf-8") as f: f.write(self.state.app_meta)

                if "[TARGET_ROUTE]" in raw_response:
                    self.state.inspiration_target_route = raw_response.split("[TARGET_ROUTE]")[1].split("[")[0].strip().lstrip(",: ").strip()
                
                if "[DATA_MODEL]" in raw_response:
                    self.state.inspiration_data_model = raw_response.split("[DATA_MODEL]")[1].split("[")[0].strip().lstrip(",: ").strip()
                    
                self.state.inspiration_requires_design = True
                self.state.inspiration_mode = "design"
                if "[REQUIRES_DESIGN]" in raw_response:
                    req_design_str = raw_response.split("[REQUIRES_DESIGN]")[1].split("[")[0].strip().upper()
                    if "FALSE" in req_design_str:
                        self.state.inspiration_requires_design = False
                        self.state.inspiration_mode = "logic"
                    elif "REFINEMENT" in req_design_str:
                        self.state.inspiration_mode = "refinement"
                        
                if "[TEST_SCENARIO]" in raw_response:
                    self.state.inspiration_test_scenario = raw_response.split("[TEST_SCENARIO]")[1].split("[")[0].strip().lstrip(",: ").strip()
                    
                logger.info(f"New Goal: {self.state.inspiration_goal} (Mode: {self.state.inspiration_mode})")
                
                # Persist this new project to the long-term archive
                self._save_to_lab_memory()
            else:
                self.state.current_status = "Evaluating product roadmap for next phase..."
                self.state.save()
                logger.info("Overseer is acting as Product Manager...")

                try: src_tree = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", "HEAD", "src/"], cwd="app", text=True)
                except Exception as e:
                    logger.warning(f"Failed to read src/ tree: {e}")
                    src_tree = "src/ tree unavailable."
                
                memory_context = ""
                if self.state.repo_memory.get("learnings"):
                    memory_context = "\nPast Learnings:\n"
                    for l in self.state.repo_memory["learnings"][-3:]:
                        status = "Success" if l['success'] else "Failure"
                        memory_context += f"- Iteration {l['iteration']} ({status}): {l['takeaways']}\n"

                last_goal = self.state.history[-1].goal if self.state.history else "Initial Scaffold"
                last_route = self.state.history[-1].target_route if self.state.history else "/"

                # Ensure we have the visual context of the app even after a restart
                if not self.app_screenshot and self.state.history and self.state.history[-1].attempts:
                    last_attempt = self.state.history[-1].attempts[-1]
                    if last_attempt.app_screenshot_path and os.path.exists(f"viewer/public/{last_attempt.app_screenshot_path}"):
                        try:
                            with open(f"viewer/public/{last_attempt.app_screenshot_path}", "rb") as f:
                                self.app_screenshot = f.read()
                        except Exception as e:
                            logger.warning(f"Failed to load last screenshot for PM review: {e}")

                next_prompt = f"""
We just successfully implemented: '{last_goal}' at route '{last_route}'. 
App Identity: {self.state.app_meta}
Current Product Phase: {self.state.product_phase}
{memory_context}

Current Codebase Files:
```text
{src_tree}
```

You are a strict, product-minded General Manager overseeing this app. You do NOT invent random features. You build a real, viable product using a strict maturity playbook:

THE PLAYBOOK:
- Phase 1: Core Loop MVP (Focus: The single primary action must work flawlessly)
- Phase 2: State & Retention (Focus: Saving data, localStorage, user memory, empty states)
- Phase 3: Vibe & Polish (Focus: Typography, spacing, framer-motion animations, responsive design)
- Phase 4: Monetization & Growth (Focus: Stripe paywalls, pricing pages, upgrade modals)

YOUR TASK:
1. Look at the Current Codebase Files and the feature we just shipped. 
2. Determine if the app is ready to graduate to the next Phase in the playbook, or if it needs to stay in the current Phase to fix gaps.
3. Decide the ONE most critical next step. 

OUTPUT FORMAT:
[NEW_PHASE]
(e.g., Phase 2: State & Retention)

[ROADMAP_UPDATE]
A brief sentence explaining why you chose this phase and what the current status is.

[SELECTED CONCEPT]
The specific engineering/design goal for the next iteration based on the Phase.

[TARGET_ROUTE]
The URL path (e.g. /settings)

[REQUIRES_DESIGN]
TRUE, FALSE, or REFINEMENT (Use REFINEMENT if the goal is fixing CSS/UI to match current assets)

[TEST_SCENARIO]
A step-by-step playwright assertion to prove it works.

[DATA_MODEL]
(Optional) Update the Firestore schema if new data structures are required.

[APP_META]
(Optional) If you are updating the product identity (e.g. Phase 3 Polish), provide the updated Name, Palette, and Typography. Otherwise, omit this tag.
"""
                next_idea = self.think(next_prompt, self.app_screenshot, temperature=0.8)
                logger.info(f"PM Roadmap Review Output:\n{next_idea}")
                self.current_brainstorm_output = next_idea
                
                if "[NEW_PHASE]" in next_idea:
                    self.state.product_phase = next_idea.split("[NEW_PHASE]")[1].split("[")[0].strip().lstrip(",: ").strip()
                if "[ROADMAP_UPDATE]" in next_idea:
                    self.state.product_roadmap = next_idea.split("[ROADMAP_UPDATE]")[1].split("[")[0].strip().lstrip(",: ").strip()
                if "[SELECTED CONCEPT]" in next_idea:
                    self.state.inspiration_goal = next_idea.split("[SELECTED CONCEPT]")[1].split("[")[0].strip().lstrip(",: ").strip()
                if "[TARGET_ROUTE]" in next_idea:
                    self.state.inspiration_target_route = next_idea.split("[TARGET_ROUTE]")[1].split("[")[0].strip().lstrip(",: ").strip()
                
                if "[DATA_MODEL]" in next_idea:
                    self.state.inspiration_data_model = next_idea.split("[DATA_MODEL]")[1].split("[")[0].strip().lstrip(",: ").strip()
                
                self.state.inspiration_requires_design = True
                self.state.inspiration_mode = "design"
                if "[REQUIRES_DESIGN]" in next_idea:
                    req_design_str = next_idea.split("[REQUIRES_DESIGN]")[1].split("[")[0].strip().upper()
                    if "FALSE" in req_design_str:
                        self.state.inspiration_requires_design = False
                        self.state.inspiration_mode = "logic"
                    elif "REFINEMENT" in req_design_str:
                        self.state.inspiration_mode = "refinement"

                if "[TEST_SCENARIO]" in next_idea:
                    self.state.inspiration_test_scenario = next_idea.split("[TEST_SCENARIO]")[1].split("[")[0].strip().lstrip(",: ").strip()
                if "[APP_META]" in next_idea:
                    meta_part = next_idea.split("[APP_META]")[1]
                    self.state.app_meta = (meta_part.split("[")[0].strip() if "[" in meta_part else meta_part.strip()).lstrip(",: ").strip()
                    with open("app/APP_META.md", "w", encoding="utf-8") as f: f.write(self.state.app_meta)

        # Record current iteration parameters immediately
        self.state.current_iteration += 1
        branch_name = f"iter-{self.state.current_iteration}"
        self.git.checkout_branch(branch_name)
        
        self.current_iteration_record = LoopIteration(
            id=self.state.current_iteration,
            timestamp=str(datetime.now()),
            goal=self.state.inspiration_goal,
            target_route=self.state.inspiration_target_route,
            data_model=self.state.inspiration_data_model,
            requires_design=self.state.inspiration_requires_design,
            test_scenario=self.state.inspiration_test_scenario,
            negative_history=[h.goal for h in self.state.history[-5:] if h.goal],
            brainstorming_output=self.current_brainstorm_output
        )
        self.state.history.append(self.current_iteration_record)
        self.state.save()
        return branch_name

    def _save_to_lab_memory(self):
        """Saves the current inspiration goal to loom_memory.json if it's new."""
        try:
            name = "Unknown"
            niche = self.state.inspiration_goal[:200]
            
            # Try to extract a name if the LLM provided one (optional based on prompt evolution)
            if "[APP_META]" in (self.current_brainstorm_output or ""):
                meta = self.current_brainstorm_output.split("[APP_META]")[1].split("[")[0].strip()
                name = meta.split("\n")[0].replace("Name:", "").strip()

            new_project = {
                "name": name,
                "niche": niche,
                "pitch": self.state.inspiration_goal,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            # Load fresh copy to avoid overwrite races
            if os.path.exists("loom_memory.json"):
                with open("loom_memory.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {"archive_count": 0, "technical_learnings": [], "past_projects": []}
            
            # Avoid duplicates
            if not any(p.get("pitch") == new_project["pitch"] for p in data.get("past_projects", [])):
                data.setdefault("past_projects", []).append(new_project)
                data["archive_count"] = len(data["past_projects"])
                
                with open("loom_memory.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                logger.info(f"Saved project '{name}' to long-term lab memory.")
        except Exception as e:
            logger.warning(f"Failed to save to loom_memory.json: {e}")

    def _step_design(self):
        if self.state.inspiration_mode == "logic":
            logger.info("Skipping Stitch design phase as inspiration_mode is logic.")
            return

        if self.state.inspiration_mode == "refinement":
            logger.info("Preserving existing design assets for refinement pass.")
            return

        self.state.current_phase = LoomPhase.DESIGN.value
        design_file = os.path.abspath("app/design/latest_design.html")

        # ITERATION 2+ (EVOLUTION)
        if self.state.current_iteration > 1 and getattr(self.state, 'stitch_project_id', None):
            logger.info(f"Iteration {self.state.current_iteration}: Designing {self.state.inspiration_mode} pass for project...")
            self.state.current_status = f"Designing {self.state.inspiration_mode} pass in existing project..."
            self.state.save()
            
            if self.state.inspiration_mode == "design":
                prompt = f"We are adding a new feature: '{self.state.inspiration_goal}'. This feature is part of the flow at: {self.state.inspiration_target_route}. Please design the UI for this feature. Maintain the established navigation, theme, and visual identity of the project: {self.state.app_meta}."
            else:
                prompt = f"We are refining the existing UI and logic for: '{self.state.inspiration_goal}'. Target route: {self.state.inspiration_target_route}. Please update the design to be more polished and consistent with the core identity: {self.state.app_meta}."
            
            screen_id = getattr(self.state, 'stitch_screen_id', None)
            screens = self.stitch.generate_or_edit_screen(
                description=prompt,
                project_id=self.state.stitch_project_id,
                screen_id=screen_id
            )
            
            if screens:
                # Clear old design files to prevent stale references
                if os.path.exists("app/design"):
                    for f in os.listdir("app/design"):
                        if f.endswith(".html") or f.endswith(".png"):
                            try: os.remove(os.path.join("app/design", f))
                            except: pass
                else:
                    os.makedirs("app/design", exist_ok=True)

                ts = int(time.time())
                for i, screen in enumerate(screens):
                    html_content = screen["html"]
                    new_screen_id = screen["screen_id"]
                    
                    # Capture all images for this screen
                    for idx, img_bytes in enumerate(screen["images"]):
                        evolved_rel_path = f"artifacts/iter_{self.state.current_iteration}_evolved_{i}_{idx}_{ts}.png"
                        with open(f"viewer/public/{evolved_rel_path}", "wb") as f:
                            f.write(img_bytes)
                        
                        # Save in app/design for Jules
                        ref_name = "reference.png" if i == 0 and idx == 0 else f"reference_{i}_{idx}.png"
                        with open(f"app/design/{ref_name}", "wb") as f:
                            f.write(img_bytes)
                            
                        if i == 0 and idx == 0:
                            self.current_iteration_record.chosen_design_path = evolved_rel_path
                            self.current_iteration_record.chosen_theme_path = evolved_rel_path
                    
                    design_name = "latest_design.html" if i == 0 else f"latest_design_{i}.html"
                    design_file = os.path.abspath(f"app/design/{design_name}")
                    with open(design_file, "w", encoding="utf-8") as f:
                        f.write(html_content)
                    
                    if i == 0:
                        self.state.stitch_screen_id = new_screen_id
                        
                self.state.save()
                
                self.git.commit(f"design: generated new screen for iter {self.state.current_iteration}")
            return

        # ITERATION 1 (REVOLUTION - 5-5-5)
        self.state.current_status = f"Overseer is generating 5 structural hypotheses for the product..."
        self.state.save()
        
        # 1. OVERSEER GENERATES DIVERGENT HYPOTHESES
        brief_prompt = f"""
You have invented the following product: '{self.state.inspiration_goal}'.
Your task is to generate 5 wildly different 'Structural Hypotheses' for how this product could be realized.

Avoid the 'Premium' trap (generic SaaS aesthetics). Instead, think about the specific materiality and UX density required:
- Is it a dense industrial tool?
- An elastic, playful playground?
- A raw, information-first terminal?
- A spatial, non-linear canvas?
- A rhythmic, narrative-driven sequence?

Provide 5 concise (1-2 sentence) design briefs. Label them [BRIEF 1] through [BRIEF 5].
"""
        brief_response = self.think(brief_prompt, temperature=0.9)
        logger.info(f"Divergent Briefs:\n{brief_response}")
        
        briefs = []
        import re
        for i in range(1, 6):
            match = re.search(f"\\[BRIEF {i}\\](.*?)(?=\\[BRIEF|$)", brief_response, re.DOTALL)
            if match: briefs.append(match.group(1).strip())
        
        if not briefs:
             briefs = ["Dense Industrial", "Elastic Playground", "Raw Information Terminal", "Spatial Canvas", "Narrative Sequence"]
        
        self.current_iteration_record.base_briefs = briefs
        self.state.save()
        
        if not self.state.stitch_project_id:
            try:
                self.state.stitch_project_id = self.stitch.create_project(self.state.project_name)
                self.state.save()
                self._update_env_file("STITCH_PROJECT_ID", self.state.stitch_project_id)
            except Exception as e:
                logger.error(f"Failed to create Stitch project: {e}")

        # 2. PARALLEL DISCOVERY (5 Independent Base Seeds in 5 Unique Projects)
        logger.info(f"Generating 5 independent base seeds in parallel...")
        self.state.current_status = "Phase 1: Generating 5 independent base seeds..."
        self.state.save()
        base_variants = [None] * 5
        self.current_iteration_record.base_seed_paths = [None] * 5
        design_prompt = f"Task: {self.state.inspiration_goal}\n\nTarget Route: {self.state.inspiration_target_route}"
        
        import concurrent.futures
        
        def generate_seed_worker(i, brief):
            try:
                unique_project_name = f"Loom {self.state.current_iteration} - Hypothesis {i+1}"
                p_id = self.stitch.create_project(unique_project_name)
                
                logger.info(f"Worker {i+1}: Generating Seed in Project {p_id}...")
                screens = self.stitch.generate_or_edit_screen(
                    description=f"{design_prompt}\n\nSTRUCTURAL HYPOTHESIS: {brief}",
                    project_id=p_id,
                    screen_id=None 
                )
                if screens:
                    win = screens[0]
                    ts = int(time.time())
                    # Capture all images but pick first as primary
                    seed_rel_path = None
                    for img_idx, img_bytes in enumerate(win["images"]):
                        path = f"artifacts/iter_{self.state.current_iteration}_seed_{i+1}_{img_idx}_{ts}.png"
                        with open(f"viewer/public/{path}", "wb") as f:
                            f.write(img_bytes)
                        if img_idx == 0: seed_rel_path = path
                    
                    self.current_iteration_record.base_seed_paths[i] = seed_rel_path
                    self.state.save()
                    
                    return {
                        "project_id": p_id, 
                        "screen_id": win["screen_id"], 
                        "html": win["html"], 
                        "img": win["images"][0] if win["images"] else None,
                        "images": win["images"],
                        "brief": brief,
                        "index": i
                    }
            except Exception as e:
                logger.error(f"Worker {i+1} failed: {e}")
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_seed = {executor.submit(generate_seed_worker, i, brief): i for i, brief in enumerate(briefs)}
            results = []
            for future in concurrent.futures.as_completed(future_to_seed):
                res = future.result()
                if res: results.append(res)

        # Sort results back to original order
        results.sort(key=lambda x: x["index"])
        base_variants = [r for r in results if r is not None]

        if not base_variants:
            raise Exception("Failed to generate any base design seeds.")

        # Overseer picks the best Base Seed
        self.state.current_status = "Selecting the winning structural hypothesis..."
        self.state.save()
        
        prompt = [f"Select the best Structural Hypothesis for: '{self.state.inspiration_goal}'.\n1. Analyze the strengths and weaknesses of each design.\n2. Explain which one best captures the 'soul' of the product.\n3. Output ONLY the integer index (1-{len(base_variants)}) on the very last line."]
        content = []
        for idx, var in enumerate(base_variants):
            prompt.append(f"Image {idx+1}: {var['brief']}")
            if var.get("img"):
                content.append({"mime_type": "image/png", "data": var["img"]})
        
        review_response = self.model.generate_content([*prompt, *content])
        self.current_iteration_record.seed_review_critique = review_response.text.strip()
        
        try:
            best_base_idx_raw = int(''.join(filter(str.isdigit, review_response.text.split("\n")[-1]))) - 1
            best_base_idx = max(0, min(len(base_variants)-1, best_base_idx_raw))
        except:
            best_base_idx = 0
            
        winning_seed = base_variants[best_base_idx]
        self.state.stitch_project_id = winning_seed["project_id"]
        screen_id = winning_seed["screen_id"]
        
        self._update_env_file("STITCH_PROJECT_ID", self.state.stitch_project_id)
        
        # Clear old design files
        if os.path.exists("app/design"):
            for f in os.listdir("app/design"):
                if f.endswith(".html") or f.endswith(".png"):
                    try: os.remove(os.path.join("app/design", f))
                    except: pass
        else:
            os.makedirs("app/design", exist_ok=True)

        with open(design_file, "w", encoding="utf-8") as f:
            f.write(winning_seed["html"])
        
        if winning_seed.get("images"):
            for img_idx, img_bytes in enumerate(winning_seed["images"]):
                ref_name = "reference.png" if img_idx == 0 else f"reference_{img_idx}.png"
                with open(os.path.join("app", "design", ref_name), "wb") as f:
                    f.write(img_bytes)
        
        self.current_iteration_record.design_screenshot_path = self.current_iteration_record.base_seed_paths[winning_seed["index"]]
        self.state.save()

        # 3. SINGLE-CALL LAYOUT REFINEMENT (5 Variants in One Call)
        logger.info("Generating 5 layout variants of the winning seed in a single call...")
        self.state.current_status = "Phase 2: Refining layout variants (5-way parallel)..."
        self.state.save()
        
        layout_variants = self.stitch.generate_variants(
            prompt=f"Explore 5 divergent layout refinements for this winning hypothesis. Focus on maximizing the intentionality of the UX for: {self.state.inspiration_goal}.",
            project_id=self.state.stitch_project_id,
            screen_id=screen_id,
            count=5,
            creative_range="EXPLORE",
            aspects=["LAYOUT"]
        )
        
        if layout_variants:
            self.current_iteration_record.design_variants_paths = []
            valid_layouts = []
            ts = int(time.time())
            for idx, var in enumerate(layout_variants):
                if not var.get("images"): continue
                # Capture all images for variant, pick first for primary path
                primary_path = None
                for img_idx, img_bytes in enumerate(var["images"]):
                    var_dest = f"viewer/public/artifacts/iter_{self.state.current_iteration}_layout_{idx+1}_{img_idx}_{ts}.png"
                    with open(var_dest, "wb") as f: f.write(img_bytes)
                    if img_idx == 0: primary_path = f"artifacts/iter_{self.state.current_iteration}_layout_{idx+1}_{img_idx}_{ts}.png"
                
                self.current_iteration_record.design_variants_paths.append(primary_path)
                valid_layouts.append(var)
            
            if valid_layouts:
                # 6-Pack Vote: Include the Base Seed as Image 1
                prompt = [f"Select the absolute best layout for: '{self.state.inspiration_goal}'.\nImage 1 is your current baseline. Images 2-6 are new variations.\n1. Evaluate the usability and intentionality of each layout.\n2. Choose the winner.\n3. Output ONLY the integer index (1-6) on the very last line."]
                layout_content = []
                
                # Image 1: The Baseline (Winner of previous phase)
                with open(f"viewer/public/{self.current_iteration_record.design_screenshot_path}", "rb") as f:
                    layout_content.append({"mime_type": "image/png", "data": f.read()})
                
                for idx, var in enumerate(valid_layouts):
                    layout_content.append({"mime_type": "image/png", "data": var["images"][0]})
                
                layout_res = self.model.generate_content([*prompt, *layout_content])
                self.current_iteration_record.layout_review_critique = layout_res.text.strip()
                try:
                    best_l_idx = int(''.join(filter(str.isdigit, layout_res.text.split("\n")[-1]))) - 1
                    if best_l_idx == 0:
                        logger.info("Overseer chose to stick with the original Base Seed layout.")
                        self.current_iteration_record.chosen_design_path = self.current_iteration_record.design_screenshot_path
                    else:
                        var_idx = best_l_idx - 1
                        screen_id = valid_layouts[var_idx]["screen_id"]
                        winning_layout = valid_layouts[var_idx]
                        self.current_iteration_record.chosen_design_path = self.current_iteration_record.design_variants_paths[var_idx]
                        
                        # Clear old design files
                        if os.path.exists("app/design"):
                            for f in os.listdir("app/design"):
                                if f.endswith(".html") or f.endswith(".png"):
                                    try: os.remove(os.path.join("app/design", f))
                                    except: pass
                        else:
                            os.makedirs("app/design", exist_ok=True)
                                
                        design_file = os.path.abspath("app/design/latest_design.html")
                        if winning_layout.get("html_content"):
                            with open(design_file, "w", encoding="utf-8") as f: f.write(winning_layout["html_content"])
                        if winning_layout.get("images"):
                            for img_idx, img_bytes in enumerate(winning_layout["images"]):
                                ref_name = "reference.png" if img_idx == 0 else f"reference_{img_idx}.png"
                                with open(os.path.join("app", "design", ref_name), "wb") as f: f.write(img_bytes)
                except Exception as e:
                    logger.warning(f"Failed to parse LLM layout index selection: {e}")
            self.state.save()

        # 4. SINGLE-CALL THEME PASS (5 Variants)
        # Always run theme exploration for Iteration 1 to establish the brand
        if self.state.current_iteration == 1:
            self._run_theme_pass(screen_id, count=5)
        else:
            logger.info("Applying existing App Meta theme to new layout...")
            screens = self.stitch.generate_or_edit_screen(
                description=f"Apply this existing visual identity strictly: {self.state.app_meta}. Maintain the current layout exactly.",
                project_id=self.state.stitch_project_id,
                screen_id=screen_id
            )
            if screens:
                # Clear old design files to prevent stale references
                if os.path.exists("app/design"):
                    for f in os.listdir("app/design"):
                        if f.endswith(".html") or f.endswith(".png"):
                            try: os.remove(os.path.join("app/design", f))
                            except: pass
                else:
                    os.makedirs("app/design", exist_ok=True)

                for i, win in enumerate(screens):
                    design_name = "latest_design.html" if i == 0 else f"latest_design_{i}.html"
                    design_file = os.path.abspath(f"app/design/{design_name}")
                    with open(design_file, "w", encoding="utf-8") as f:
                        f.write(win["html"])
                    
                    for idx, img_bytes in enumerate(win["images"]):
                        ref_name = "reference.png" if i == 0 and idx == 0 else f"reference_{i}_{idx}.png"
                        with open(os.path.abspath(f"app/design/{ref_name}"), "wb") as f:
                            f.write(img_bytes)
                            
                    if i == 0:
                        screen_id = win["screen_id"]

        self.state.stitch_screen_id = screen_id
        self.state.save()
        self.git.commit(f"design: unconstrained 5-5-5 discovery for iter {self.state.current_iteration}")

    def _run_theme_pass(self, screen_id, count=5):
        logger.info(f"Conducting Theme Pass with {count} variants...")
        self.state.current_status = f"Phase 3: Exploring {count} color and typography themes..."
        self.state.save()
        
        theme_variants = self.stitch.generate_variants(
            prompt=f"Explore {count} completely distinct color palettes, dark/light modes, and typography combinations for this layout. The goal is a high-intentionality feel for: {self.state.inspiration_goal}. Do not change the layout structure.",
            project_id=self.state.stitch_project_id,
            screen_id=screen_id,
            count=count,
            creative_range="EXPLORE",
            aspects=["COLOR_SCHEME", "TEXT_FONT"]
        )
        
        if theme_variants:
            self.current_iteration_record.theme_variants_paths = []
            valid_themes = []
            t_ts = int(time.time())
            for idx, var in enumerate(theme_variants):
                if not var.get("images"): continue
                primary_path = None
                for img_idx, img_bytes in enumerate(var["images"]):
                    var_dest = f"viewer/public/artifacts/iter_{self.state.current_iteration}_theme_{idx+1}_{img_idx}_{t_ts}.png"
                    with open(var_dest, "wb") as f: f.write(img_bytes)
                    if img_idx == 0: primary_path = f"artifacts/iter_{self.state.current_iteration}_theme_{idx+1}_{img_idx}_{t_ts}.png"
                
                self.current_iteration_record.theme_variants_paths.append(primary_path)
                valid_themes.append(var)
            
            if valid_themes:
                # 6-Pack Vote: Include the selected Layout as Image 1
                prompt = [f"Select the absolute best visual theme for: '{self.state.inspiration_goal}'.\nImage 1 is your current baseline. Images 2-6 are new color/typography explorations.\n1. Pick the best theme.\n2. Define [APP_META] (Name, Palette, Typography) for this winning choice.\nOutput index (1-6) on last line."]
                theme_content = []
                
                # Image 1: The Baseline (Selected Layout from previous phase)
                design_ref = os.path.abspath("app/design/reference.png")
                if os.path.exists(design_ref):
                    with open(design_ref, "rb") as f:
                        theme_content.append({"mime_type": "image/png", "data": f.read()})
                
                for idx, var in enumerate(valid_themes):
                    theme_content.append({"mime_type": "image/png", "data": var["images"][0]})
                
                theme_res = self.model.generate_content([*prompt, *theme_content])
                theme_text = theme_res.text.strip()
                self.current_iteration_record.theme_review_critique = theme_text
                
                if "[APP_META]" in theme_text:
                    meta_part = theme_text.split("[APP_META]")[1]
                    self.state.app_meta = meta_part.split("[")[0].strip() if "[" in meta_part else meta_part.strip()
                    with open("app/APP_META.md", "w", encoding="utf-8") as f: f.write(self.state.app_meta)
                
                try:
                    best_t_idx = int(''.join(filter(str.isdigit, theme_text.split("\n")[-1]))) - 1
                    if best_t_idx == 0:
                        logger.info("Overseer chose to stick with the baseline theme.")
                    else:
                        var_idx = best_t_idx - 1
                        chosen_t = valid_themes[var_idx]
                        self.current_iteration_record.chosen_theme_path = self.current_iteration_record.theme_variants_paths[var_idx]
                        
                        # Clear old design files
                        if os.path.exists("app/design"):
                            for f in os.listdir("app/design"):
                                if f.endswith(".html") or f.endswith(".png"):
                                    try: os.remove(os.path.join("app/design", f))
                                    except: pass
                        else:
                            os.makedirs("app/design", exist_ok=True)
                                
                        design_file = os.path.abspath("app/design/latest_design.html")
                        if chosen_t.get("html_content"):
                            with open(design_file, "w", encoding="utf-8") as f: f.write(chosen_t["html_content"])
                        if chosen_t.get("images"):
                            for img_idx, img_bytes in enumerate(chosen_t["images"]):
                                ref_name = "reference.png" if img_idx == 0 else f"reference_{img_idx}.png"
                                with open(os.path.join("app", "design", ref_name), "wb") as f: f.write(img_bytes)
                except Exception as e:
                    logger.warning(f"Failed to parse LLM theme index selection: {e}")
            self.state.save()

    def _step_implementation(self, branch_name):
        self.state.current_phase = LoomPhase.IMPLEMENTATION.value
        
        # 1. Autonomous Database Provisioning (The Data Soul)
        if self.state.inspiration_data_model:
            logger.info("Overseer is provisioning PocketBase schema...")
            self.state.current_status = "Provisioning database schema..."
            self.state.save()
            
            try:
                from loom.environment.pocketbase import DatabaseProvisioner
                provisioner = DatabaseProvisioner(pb_url=self.pb_url)
                
                # Ask LLM to translate plain text data model to PocketBase JSON Schema
                schema_prompt = f"""
Convert the following data model description into a JSON array of PocketBase collection definitions.
Data Model: {self.state.inspiration_data_model}

Rules:
1. Each object in the array must represent a collection.
2. Required fields for each collection: "name" (string), "type" ("base" or "auth"), "schema" (array of field definition objects).
3. Valid field types: "text", "number", "bool", "email", "url", "date", "select", "json", "file", "relation".
4. Set "listRule", "viewRule", "createRule", "updateRule", "deleteRule" to "" (empty string = public access) for easy prototyping.
5. Return ONLY valid JSON, no markdown blocks.

Example output:
[
  {{
    "name": "posts",
    "type": "base",
    "schema": [
      {{"name": "title", "type": "text", "required": true}},
      {{"name": "views", "type": "number", "required": false}}
    ],
    "listRule": "", "viewRule": "", "createRule": "", "updateRule": "", "deleteRule": ""
  }}
]
"""
                schema_json_str = self.model.generate_content(schema_prompt).text.strip()
                # Clean markdown if present
                schema_json_str = schema_json_str.replace("```json", "").replace("```", "").strip()
                
                import json
                schema_json = json.loads(schema_json_str)
                
                success = provisioner.provision_schema(schema_json)
                if success:
                    logger.info("Successfully provisioned PocketBase schema.")
                else:
                    logger.warning("Failed to provision some or all PocketBase collections.")
            except Exception as e:
                logger.error(f"Failed to provision database: {e}")

        max_attempts = 50
        current_attempt = 1
        while current_attempt <= max_attempts:
            logger.info(f"--- Attempt {current_attempt}/{max_attempts} for Iteration {self.state.current_iteration} ---")
            self.state.current_status = f"Jules is coding (Attempt {current_attempt})..."
            self.state.save()
            
            attempt_branch = f"{branch_name}-att{current_attempt}"
            try: self.git._run(["git", "checkout", "-b", attempt_branch], cwd="app")
            except Exception: self.git._run(["git", "checkout", attempt_branch], cwd="app")

            task_prompt = self._get_jules_prompt(current_attempt)
            self.git.push_branch(attempt_branch)
            owner, repo_name = self._get_repo_info()
            self.state.active_jules_prompt = task_prompt
            self.state.save()

            try:
                self.jules.run_task(task_prompt, owner, repo_name, attempt_branch, 
                                   activity_callback=lambda act, url: self._update_jules_state(act, url))
                self.git.commit(f"feat: implementation attempt {current_attempt}")
                self.git.push_branch(attempt_branch)
            except Exception as e:
                logger.error(f"Build failed: {e}")
            finally:
                self.state.active_jules_prompt = None
                self.state.save()
            
            self._save_patch_artifact(current_attempt)
            self._evaluate_iteration(current_attempt, attempt_branch)
            
            if self.happiness_score >= 8: break
            current_attempt += 1

    def _get_jules_prompt(self, attempt):
        memory_context = ""
        if self.state.repo_memory.get("learnings"):
            memory_context = "\nPast Learnings:\n"
            for l in self.state.repo_memory["learnings"][-3:]:
                status = "Success" if l['success'] else "Failure"
                memory_context += f"- Iteration {l['iteration']} ({status}): {l['takeaways']}\n"

        if attempt == 1:
            data_model_context = f"\nData Model (PocketBase Schema):\n{self.state.inspiration_data_model}\n" if self.state.inspiration_data_model else ""
            if self.state.inspiration_mode == "design":
                return f"""
Implement the design for '{self.state.inspiration_goal}'.
App Identity: {self.state.app_meta}
Target Route: {self.state.inspiration_target_route}
{data_model_context}
{memory_context}

The design files are in app/design. 
CRITICAL RULES:
1. Integrate this new feature into the existing application natively using the established design system (Tailwind classes, layout, components).
2. The target flow/location is: '{self.state.inspiration_target_route}'. If this requires a new page, set up React Router without breaking existing pages AND add a visible link to it in the main app navigation so the user can reach it. If it is a modal/overlay, integrate it cleanly into the current view.
3. If a Data Model is provided above, you MUST use the `pocketbase` npm package to make the application state persistent. Assume the PocketBase server is running on port 8090 of the same host as the application. Initialize the client using `new PocketBase(window.location.protocol + "//" + window.location.hostname + ":8090")`. Provide a clean API or hook for the UI to interact with.
4. All new UI states, overlays, drawers, or modals MUST be deep-linkable and controllable via URL search parameters (e.g., `/?view=settings` or `/?modal=library`).
5. You MUST append a new Playwright integration test block (`test('...', async ({{ page }}) => {{...}})`) to `app/tests/verify.spec.ts` that implements this exact verification scenario: "{self.state.inspiration_test_scenario}". Do NOT delete existing tests.
6. CRITICAL: At the end of your newly added test (after the assertions pass), you MUST take a screenshot of the active feature using `await page.screenshot({{ path: 'evidence.png' }});`. This image is required to prove the feature works visually.
"""
            elif self.state.inspiration_mode == "refinement":
                return f"""
Refine the implementation of '{self.state.inspiration_goal}'.
App Identity: {self.state.app_meta}
Target Route: {self.state.inspiration_target_route}
{data_model_context}
{memory_context}

The design is LOCKED. Do NOT expect new design assets. Your task is to refine the existing CSS, layout, and logic to better match the current files in `app/design` and fix any discrepancies.

CRITICAL RULES:
1. Focus on visual and functional refinement of the existing '{self.state.inspiration_target_route}' route.
2. If a Data Model is provided, ensure the PocketBase persistence logic is robust and correctly reflects the schema.
3. You MUST update the Playwright integration test in `app/tests/verify.spec.ts` to ensure it continues to pass with these refinements.
4. CRITICAL: At the end of the test, you MUST take a screenshot of the active feature using `await page.screenshot({{ path: 'evidence.png' }});`.
"""
            else:
                return f"""
Implement the following architectural/logic feature: '{self.state.inspiration_goal}'.
App Identity: {self.state.app_meta}
Target Route: {self.state.inspiration_target_route}
{data_model_context}
{memory_context}

CRITICAL RULES:
1. This is a LOGIC ONLY update. Do NOT alter the visual design, CSS, or layout.
2. Focus purely on the underlying React logic, state management, or architecture as requested.
3. If a Data Model is provided, you MUST implement the corresponding persistence logic using the `pocketbase` SDK connecting to port 8090 of the current host (`window.location.hostname`).
4. You MUST append a new Playwright integration test block to `app/tests/verify.spec.ts` that implements this exact verification scenario: "{self.state.inspiration_test_scenario}". Do NOT delete existing tests.
5. CRITICAL: At the end of your newly added test (after the assertions pass), you MUST take a screenshot of the active feature using `await page.screenshot({{ path: 'evidence.png' }});`."""
        else:
            past_critiques = ""
            if self.current_iteration_record and self.current_iteration_record.attempts:     
                last_att = self.current_iteration_record.attempts[-1]
                past_critiques += f"\nPrevious Attempt {last_att.attempt_number} (Score: {last_att.score}/10) Critique:\n{last_att.critique}\n"
            
            data_model_context = f"\nData Model (PocketBase Schema):\n{self.state.inspiration_data_model}\n" if self.state.inspiration_data_model else ""
            return f"""Refine the implementation. 
Meta: {self.state.app_meta}. 
Route: {self.state.inspiration_target_route}. 
{data_model_context}
{memory_context}

CRITICAL RULES:
1. You MUST include or update the Playwright test in `app/tests/verify.spec.ts`.
2. Review the following feedback/errors from the previous attempt. If a Playwright test failed, fix the React code or the test script to resolve the error.

Feedback:
{past_critiques}
"""

    def _update_jules_state(self, action, url):
        self.state.active_jules_action = action
        self.state.active_jules_url = url
        self.state.save()

    def _save_patch_artifact(self, attempt):
        patch_src = "app/jules.patch"
        self.patch_dest_rel = None
        if os.path.exists(patch_src):
            ts = int(time.time())
            patch_dest = f"viewer/public/artifacts/iter_{self.state.current_iteration}_att_{attempt}_{ts}.patch"
            shutil.copy(patch_src, patch_dest)
            self.patch_dest_rel = f"artifacts/iter_{self.state.current_iteration}_att_{attempt}_{ts}.patch"

    def _evaluate_iteration(self, attempt, branch):
        self.state.current_phase = LoomPhase.VALIDATION.value
        logger.info(f"[bold cyan]Evaluating Attempt {attempt}...[/bold cyan]", extra={"markup": True})
        self.state.current_status = f"Evaluating (Attempt {attempt})..."
        self.state.save()
        
        # Reset score/critique for this attempt
        self.happiness_score = 0
        self.last_critique = ""
        self.app_screenshot = None
        self.app_screenshot_path = None

        try:
            # Build check
            build_success, build_error = self._run_build()
            if not build_success:
                logger.error(f"Build failed for attempt {attempt}: {build_error}")
                self.happiness_score, self.last_critique = 0, f"Build error: {build_error}"
            else:
                logger.info("Build successful.")
                # Test check
                test_success, test_error = self._run_tests(attempt)
                if not test_success:
                    logger.error(f"Tests failed for attempt {attempt}: {test_error}")
                    self.happiness_score, self.last_critique = 0, f"Test error: {test_error}"
                else:
                    logger.info("Tests passed.")
                    # Vision check
                    if self.state.inspiration_requires_design:
                        self.happiness_score, self.last_critique, self.app_screenshot = self.evaluate_happiness(target_route=self.state.inspiration_target_route)
                    else:
                        self.happiness_score, self.last_critique = 10, "Logic update successful."
                    
                    # Arch check
                    if self.happiness_score >= 8:
                        arch_score, arch_critique = self.evaluate_architecture(branch)
                        if arch_score < 8:
                            self.happiness_score, self.last_critique = arch_score, f"Visuals good, arch bad: {arch_critique}"
        except Exception as e:
            logger.error(f"Evaluation crashed: {e}")
            self.happiness_score, self.last_critique = 0, f"Evaluation error: {str(e)}"

        # ALWAYS Record attempt
        self._record_attempt(attempt)

    def _run_build(self):
        try:
            subprocess.run(["npm", "install", "--no-audit", "--no-fund"], cwd="app", check=True, capture_output=True, text=True, shell=(os.name == 'nt'))
            subprocess.run(["npm", "run", "build"], cwd="app", check=True, capture_output=True, text=True, shell=(os.name == 'nt'))
            return True, ""
        except subprocess.CalledProcessError as e: return False, e.stderr or e.stdout
        except Exception as e: return False, str(e)

    def _run_tests(self, attempt):
        self.phoenix.spawn()
        self.phoenix.wait_for_ready()
        try:
            # Install playwright browsers if not present
            subprocess.run(["npx", "playwright", "install", "chromium"], cwd="app", check=True, capture_output=True, text=True, shell=(os.name == 'nt'))
            result = subprocess.run(["npx", "playwright", "test"], cwd="app", capture_output=True, text=True, shell=(os.name == 'nt'))
            
            # Check for Evidence
            if os.path.exists("app/evidence.png"):
                ts = int(time.time())
                evidence_path = f"viewer/public/artifacts/iter_{self.state.current_iteration}_attempt_{attempt}_evidence_{ts}.png"
                shutil.move("app/evidence.png", evidence_path)
                # Store relative path for UI
                self.app_screenshot_path = f"artifacts/iter_{self.state.current_iteration}_attempt_{attempt}_evidence_{ts}.png"
                logger.info(f"Evidence captured: {evidence_path}")
            
            return result.returncode == 0, result.stderr or result.stdout
        except Exception as e:
            return False, str(e)
        finally:
            self.phoenix.kill()

    def _record_attempt(self, attempt):
        app_screenshot_path = None
        if self.app_screenshot:
            ts = int(time.time())
            app_screenshot_path = f"artifacts/iter_{self.state.current_iteration}_attempt_{attempt}_app_{ts}.png"
            with open(f"viewer/public/{app_screenshot_path}", "wb") as f:
                f.write(self.app_screenshot)
        
        attempt_record = AttemptRecord(
            attempt_number=attempt,
            prompt_used=self._get_jules_prompt(attempt),
            app_screenshot_path=app_screenshot_path,
            jules_patch_path=self.patch_dest_rel,
            score=self.happiness_score,
            critique=self.last_critique
        )
        self.current_iteration_record.attempts.append(attempt_record)
        self.current_iteration_record.happiness_score = self.happiness_score
        self.state.save()

    def _step_reflection(self):
        self.state.current_phase = LoomPhase.REFLECTION.value
        logger.info("Conducting Reflection Pass...")
        self.state.current_status = "Reflecting on iteration..."
        self.state.save()
        
        reflection_prompt = f"""
We just completed an iteration attempting to implement: '{self.state.inspiration_goal}'.
Final Happiness Score: {self.happiness_score}/10
Final Critique: {self.last_critique}
Final App Meta: {self.state.app_meta}

Based on this outcome, provide a brief summary of what we learned. Format as a single concise paragraph.
"""
        learnings = self.think(reflection_prompt)
        logger.info(f"Learnings:\n{learnings}")
        
        if "learnings" not in self.state.repo_memory:
            self.state.repo_memory["learnings"] = []
        self.state.repo_memory["learnings"].append({
            "iteration": self.state.current_iteration,
            "goal": self.state.inspiration_goal,
            "success": self.happiness_score >= 8,
            "takeaways": learnings
        })
        self.state.save()

    def _step_decision(self, branch):
        self.state.current_phase = LoomPhase.DECISION.value
        if self.happiness_score >= 8:
            logger.info("Happiness achieved! Merging to main.")
            self.git.checkout_branch("main")
            try:
                self.git._run(["git", "merge", branch], cwd="app")
                self.git.push_branch("main")
                
                self.state.current_status = "Merge successful. Preparing for next loop..."
                
                # Clear the inspiration goal so the next loop triggers _step_inspiration again
                self.state.inspiration_goal = ""
                self.state.inspiration_target_route = "/"
                self.state.inspiration_test_scenario = ""
                self.state.inspiration_requires_design = True
                
                self.state.save()
            except Exception as e:
                logger.error(f"Merge to main failed: {e}. Resetting main.")
                self.git._run(["git", "reset", "--hard", "origin/main"], cwd="app")
        else:
            logger.info("Max attempts reached. Abandoning iteration.")
            self.git.checkout_branch("main")
            self.git._run(["git", "reset", "--hard", "origin/main"], cwd="app")
            self.git._run(["git", "clean", "-fd"], cwd="app")
            
            # If we don't have any previous successful iterations, the genesis project failed.
            # We must wipe the design identity so the next loop starts a fresh genesis project.
            if not any(h.happiness_score >= 8 for h in self.state.history[:-1]):
                logger.warning("Genesis project failed. Resetting design state to restart 5-5-5 genesis.")
                self.state.stitch_project_id = None
                self.state.stitch_screen_id = None
                self.state.app_meta = ""
                self.state.product_phase = "Phase 1: Core Loop MVP"
                self.state.product_roadmap = ""
                if os.path.exists("app/APP_META.md"):
                    try: os.remove("app/APP_META.md")
                    except: pass
            
            self.state.inspiration_goal = ""
            self.state.inspiration_target_route = "/"
            self.state.inspiration_test_scenario = ""
            self.state.inspiration_requires_design = True
            self.state.save()
