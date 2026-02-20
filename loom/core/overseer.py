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
            self.model = genai.GenerativeModel('gemini-2.5-pro')

    def think(self, context: str) -> str:
        """Consults the LLM for the next move."""
        if not hasattr(self, 'model'): return "Mock thought: Proceed."
        response = self.model.generate_content(f"You are the Overseer of Project Loom, an autonomous software factory. Context: {context}")
        return response.text

    def evaluate_happiness(self) -> int:
        score = 10 
        try:
            self.phoenix.spawn()
            self.phoenix.wait_for_ready()
            logger.info("Phoenix Server is up. App is running.")
            # TODO: Implement Vision/Sentry Playwright checks here
        except Exception as e:
            logger.error(f"Happiness Check Failed: {e}")
            score = 0
        finally:
            self.phoenix.kill()
        return score

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
            self.stitch.generate_screen(self.state.inspiration_goal)
            self.git.commit(f"design: stitch output for iter {self.state.current_iteration}")
            
            # Push branch so Jules can see it
            self.git.push_branch(branch_name)
            owner, repo_name = self._get_repo_info()
            
            # 4. Build (Jules)
            task_prompt = f"Implement the design for '{self.state.inspiration_goal}' using React, Vite, and Tailwind CSS. The design files are in app/design. Use strict TypeScript. Return a patch that updates app/src/App.tsx or other relevant files."
            try:
                self.jules.run_task(task_prompt, owner, repo_name, branch_name)
                self.git.commit(f"feat: jules implementation for iter {self.state.current_iteration}")
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
                self.git.push_branch("main")
                
                logger.info("Brainstorming next addition to keep the build going...")
                next_prompt = f"""
We just successfully implemented: '{self.state.inspiration_goal}'. 
Generate a short, single sentence idea for the next small feature, visual improvement, or iteration to add to this app. Be creative but keep it simple.
"""
                next_idea = self.think(next_prompt)
                lines = [l.strip() for l in next_idea.strip().split("\n") if l.strip()]
                self.state.inspiration_goal = lines[-1] if lines else "Add a settings panel."
                logger.info(f"Next Idea: {self.state.inspiration_goal}")
            else:
                logger.info("Unhappy. Retrying in next iteration...")
            
            logger.info("Waiting 10 seconds before next loop...")
            time.sleep(10)
