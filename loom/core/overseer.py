import os
import time
import logging
from datetime import datetime
import google.generativeai as genai

from loom.core.state import ConductorState, LoopIteration
from loom.environment.git import GitClient
from loom.environment.phoenix import PhoenixServer
from loom.agents.stitch import StitchClient
from loom.agents.jules import JulesClient

from dotenv import load_dotenv
load_dotenv(override=True)

logger = logging.getLogger("loom")

class Overseer:
    def __init__(self):
        self.state = ConductorState.load()
        self.git = GitClient()
        self.jules = JulesClient()
        self.stitch = StitchClient()
        self.phoenix = PhoenixServer()
        
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.warning("GEMINI_API_KEY not found. Overseer will be lobotomized.")
        else:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-3.1-pro-preview')

    def think(self, context: str, image_data: bytes = None) -> str:
        """Consults the LLM for the next move."""
        if not hasattr(self, 'model'): return "Mock thought: Proceed."
        
        prompt = f"You are the Overseer of Project Loom, an autonomous software factory. Context: {context}"
        if image_data:
            content = [prompt, {"mime_type": "image/png", "data": image_data}]
            response = self.model.generate_content(content)
        else:
            response = self.model.generate_content(prompt)
        return response.text

    def _take_screenshot(self, url_or_path: str, wait_ms: int = 2000) -> bytes:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            if url_or_path.startswith("http"):
                page.goto(url_or_path)
            else:
                # Handle Windows paths for file:// URIs
                clean_path = url_or_path.replace('\\', '/')
                page.goto(f"file:///{clean_path}")
            page.wait_for_timeout(wait_ms)
            screenshot = page.screenshot()
            browser.close()
            return screenshot

    def evaluate_happiness(self) -> tuple[int, str, bytes]:
        score = 10 
        critique = "No critique."
        app_screenshot = None
        try:
            self.phoenix.spawn()
            self.phoenix.wait_for_ready()
            logger.info("Phoenix Server is up. App is running. Verifying with Vision...")
            
            try:
                app_screenshot = self._take_screenshot(f"http://localhost:{self.phoenix.port}")
                design_path = os.path.abspath("app/design/latest_design.html")
                design_screenshot = self._take_screenshot(design_path, wait_ms=500) if os.path.exists(design_path) else None
                
                if hasattr(self, 'model'):
                    prompt = [
                        f"You are the Overseer. Your goal was: '{self.state.inspiration_goal}'.\n",
                        "The first image is the actual React app running."
                    ]
                    content = [{"mime_type": "image/png", "data": app_screenshot}]
                    
                    if design_screenshot:
                        prompt.append("The second image is the intended design.")
                        content.append({"mime_type": "image/png", "data": design_screenshot})
                        
                    prompt.append("Score how well the app matches the goal (and the design if provided) from 0 to 10. Output ONLY the integer score on the first line, followed by a brief critique on the next lines.")
                    
                    response = self.model.generate_content([*prompt, *content])
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
        # Extract owner and repo from remote url
        url = self.git.get_remote_url()
        # example: https://github.com/watkajtys/ouroboros-refine-1771571544.git
        parts = url.split("/")
        repo = parts[-1].replace(".git", "")
        owner = parts[-2]
        return owner, repo

    def loop(self):
        logger.info("[bold green]Starting Loom Loop...[/bold green]", extra={"markup": True})
        
        # Ensure we have a remote repo for Jules to read from
        self.git.ensure_remote()
        
        while True:
            # 1. Inspiration
            if not self.state.inspiration_goal:
                logger.info("Generating initial open-ended inspiration goal...")
                prompt = """
We are starting a brand new React application (using Vite and Tailwind CSS).
1. Generate 3 distinct ideas for a web application. There are no constraints on complexity, be as creative or ambitious as you like.
2. Weigh the pros and cons of each based on their potential for an interesting UI and functional depth.
3. Rank them from 1 to 3.
4. Pick the #1 ranked idea and output ONLY a single, clear sentence describing it. This will be our initial Inspiration Goal.
"""
                raw_response = self.think(prompt)
                # Take the last non-empty line as the goal assuming LLM might be chatty despite "ONLY"
                lines = [l.strip() for l in raw_response.strip().split("\n") if l.strip()]
                self.state.inspiration_goal = lines[-1] if lines else "Create a futuristic dashboard."
                logger.info(f"New Goal: {self.state.inspiration_goal}")

            # 2. Iteration Setup
            self.state.current_iteration += 1
            branch_name = f"iter-{self.state.current_iteration}"
            self.git.checkout_branch(branch_name)
            
            # 3. Design (Stitch)
            if not self.state.stitch_project_id:
                try:
                    self.state.stitch_project_id = self.stitch.create_project(self.state.project_name)
                    self.state.save()
                except Exception as e:
                    logger.error(f"Failed to create Stitch project: {e}")
            
            try:
                design_file, screen_id = self.stitch.generate_or_edit_screen(
                    description=self.state.inspiration_goal,
                    project_id=self.state.stitch_project_id or os.getenv("STITCH_PROJECT_ID", ""),
                    screen_id=self.state.stitch_screen_id
                )
                if screen_id:
                    self.state.stitch_screen_id = screen_id
                    self.state.save()
            except Exception as e:
                logger.error(f"Failed to generate screen: {e}")
                
            self.git.commit(f"design: stitch output for iter {self.state.current_iteration}")
            
            # Inner Refinement Loop
            max_attempts = 3
            current_attempt = 1
            last_critique = ""
            happiness = 0

            while current_attempt <= max_attempts:
                logger.info(f"--- Attempt {current_attempt}/{max_attempts} for Iteration {self.state.current_iteration} ---")
                
                # 4. Build (Jules)
                if current_attempt == 1:
                    task_prompt = f"Implement the design for '{self.state.inspiration_goal}' using React, Vite, and Tailwind CSS. The design files (HTML and reference screenshot) are in app/design. Use strict TypeScript. Return a patch that updates app/src/App.tsx or other relevant files."
                else:
                    task_prompt = f"Refine the implementation of '{self.state.inspiration_goal}'. The previous attempt had a Happiness Score of {happiness}/10. Please fix the following issues noted by the Overseer:\n\n{last_critique}\n\nThe reference design files remain in app/design. Focus on architectural accuracy and visual fidelity."

                # Push current state of branch so Jules can see it (including previous failed attempts)
                self.git.push_branch(branch_name)
                owner, repo_name = self._get_repo_info()

                try:
                    self.jules.run_task(task_prompt, owner, repo_name, branch_name)
                    self.git.commit(f"feat: jules implementation attempt {current_attempt}")
                except Exception as e:
                    logger.error(f"Build failed: {e}")
                
                # 5. Evaluate
                happiness, last_critique, app_screenshot = self.evaluate_happiness()
                logger.info(f"Happiness Score: {happiness}/10")
                
                # 6. Save Iteration Data
                iteration_record = LoopIteration(
                    id=self.state.current_iteration,
                    timestamp=str(datetime.now()),
                    goal=self.state.inspiration_goal,
                    happiness_score=happiness,
                    critiques=[last_critique]
                )
                self.state.history.append(iteration_record)
                self.state.save()

                if happiness >= 8:
                    break
                
                current_attempt += 1
                logger.info("Happiness not achieved. Preparing for refinement...")

            # 7. Final Decision for the Iteration
            if happiness >= 8:
                logger.info("Happiness achieved! Merging to main.")
                self.git.checkout_branch("main")
                try:
                    self.git._run(["git", "merge", branch_name], cwd="app")
                    self.git.push_branch("main")
                    
                    logger.info("Brainstorming next addition to keep the build going...")
                    next_prompt = f"""
We just successfully implemented: '{self.state.inspiration_goal}'. 
Look at the attached screenshot of the current application. Based on its visual layout and purpose, what is one specific, logical new feature or improvement we should add to the UI? 
Output ONLY a single, clear sentence describing this next iteration. Be creative but keep it simple.
"""
                    next_idea = self.think(next_prompt, app_screenshot)
                    lines = [l.strip() for l in next_idea.strip().split("\n") if l.strip()]
                    self.state.inspiration_goal = lines[-1] if lines else "Add a settings panel."
                    logger.info(f"Next Idea: {self.state.inspiration_goal}")
                except Exception as e:
                    logger.error(f"Merge to main failed: {e}. Resetting main.")
                    self.git._run(["git", "reset", "--hard", "origin/main"], cwd="app")
            else:
                logger.info("Max attempts reached without achieving happiness. Abandoning iteration and returning to main.")
                self.git.checkout_branch("main")
                self.git._run(["git", "reset", "--hard", "origin/main"], cwd="app")
                self.git._run(["git", "clean", "-fd"], cwd="app")
            
            logger.info("Waiting 10 seconds before next loop...")
            time.sleep(10)
