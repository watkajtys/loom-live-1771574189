import os
import shutil
import time
import logging
from datetime import datetime
import google.generativeai as genai
import subprocess

from loom.core.state import ConductorState, LoopIteration, AttemptRecord
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
        
        # Prime state from environment if missing
        if not self.state.stitch_project_id and os.getenv("STITCH_PROJECT_ID"):
            self.state.stitch_project_id = os.getenv("STITCH_PROJECT_ID")
            self.state.save()
            logger.info(f"Primed Stitch Project ID from environment: {self.state.stitch_project_id}")
        
        # Ensure artifacts directory exists
        os.makedirs("viewer/public/artifacts", exist_ok=True)
        
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.warning("GEMINI_API_KEY not found. Overseer will be lobotomized.")
        else:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-3.1-pro-preview')

    def think(self, context: str, image_data: bytes = None) -> str:
        """Consults the LLM for the next move."""
        if not hasattr(self, 'model'): return "Mock thought: Proceed."
        
        prompt = f"You are the Overseer of Project Loom. We're building software together and you keep everything moving. Context: {context}"
        if image_data:
            content = [prompt, {"mime_type": "image/png", "data": image_data}]
            response = self.model.generate_content(content)
        else:
            response = self.model.generate_content(prompt)
        return response.text

    def _take_screenshot(self, url_or_path: str, wait_ms: int = 2000, return_logs: bool = False):
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
        logger.info("Evaluating architectural best practices...")
        try:
            diff_output = self.git._run(["git", "diff", f"main...{branch_name}"], cwd="app")
            
            if not diff_output.strip():
                return 10, "No code changes detected to review."
                
            prompt = f"""
You are an expert Principal Software Engineer acting as the Architectural Reviewer for Project Loom.
The application is built using React, Vite, Tailwind CSS, and strict TypeScript.
Please review the following git diff containing the changes made in this iteration.

Evaluate the changes based on:
1. Technical best practices (React hooks, state management, pure functions).
2. Modularity and separation of concerns (are components getting too large?).
3. Maintainability and readability.
4. Any potential performance bottlenecks (unnecessary re-renders, complex layout thrashing).

Provide a concise, highly technical architectural critique (under 250 words). Focus strictly on the code quality, not the visual design.
Finally, give the architecture a score from 1 to 10. Output ONLY the integer score on the very last line of your response.

GIT DIFF:
```diff
{diff_output[:10000]} # Truncated to avoid token limits if it's massive
```
"""
            review_response = self.think(prompt)
            review_text = review_response.strip()
            logger.info(f"Architectural Critique:\n{review_text}")
            
            lines = [l.strip() for l in review_text.split('\n') if l.strip()]
            score_str = ''.join(filter(str.isdigit, lines[-1]))
            score = int(score_str) if score_str else 5
            score = max(1, min(10, score))
            
            return score, review_text
            
        except Exception as e:
            logger.error(f"Failed to evaluate architecture: {e}")
            return 5, f"Architectural evaluation failed: {str(e)}"

    def evaluate_happiness(self) -> tuple[int, str, bytes]:
        score = 10 
        critique = "No critique."
        app_screenshot = None
        try:
            self.phoenix.spawn()
            self.phoenix.wait_for_ready()
            logger.info("Phoenix Server is up. App is running. Verifying with Vision...")
            
            try:
                app_screenshot, console_logs = self._take_screenshot(f"http://localhost:{self.phoenix.port}", return_logs=True)
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
                    
                    if console_logs:
                        logs_str = "\n".join(console_logs[:20]) # Limit to 20 lines
                        prompt.append(f"\nCRITICAL: The browser console reported the following logs/errors. Factor these heavily into your score and critique:\n{logs_str}")

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

    def loop(self):
        logger.info("[bold green]Starting Loom Loop...[/bold green]", extra={"markup": True})
        self.git.ensure_remote()
        
        current_brainstorm_output = None
        
        while True:
            # 1. Inspiration
            if not self.state.inspiration_goal:
                self.state.current_status = "Brainstorming initial goal..."
                self.state.save()
                logger.info("Generating initial open-ended inspiration goal...")
                prompt = f"""
We are starting a brand new React application (using Vite and Tailwind CSS).
Your task is to generate the seed concept for this project.

[Random Seed for Variety: {int(time.time())}]

1. Generate exactly 3 highly distinct, creative ideas for a web application. It can be a real, useful tool or something highly experimental and interesting. Do not constrain yourself to specific themes, but prioritize ideas that would have a visually compelling UI. 
Think outside the box. What would be interesting or useful for users?
2. For each idea, briefly weigh the pros and cons based on its potential for a stunning UI and deep functionality.
3. Rank the 3 ideas from 1st (best) to 3rd.
4. Output the 1st ranked idea as a detailed paragraph describing the app's architecture, aesthetic, and core functionality. 

Format your final choice clearly starting with "SELECTED CONCEPT:" so it can be reliably parsed.
"""
                raw_response = self.think(prompt)
                logger.info(f"Brainstorming Output:\n{raw_response}")
                current_brainstorm_output = raw_response
                
                if "SELECTED CONCEPT:" in raw_response:
                    self.state.inspiration_goal = raw_response.split("SELECTED CONCEPT:")[1].strip()
                else:
                    lines = [l.strip() for l in raw_response.strip().split("\n") if l.strip()]
                    self.state.inspiration_goal = lines[-1] if lines else "Create a futuristic dashboard."
                    
                logger.info(f"New Goal: {self.state.inspiration_goal}")
                self.state.save()

            # 2. Iteration Setup
            self.state.current_iteration += 1
            branch_name = f"iter-{self.state.current_iteration}"
            self.git.checkout_branch(branch_name)
            
            # Setup Iteration Record
            iteration_record = LoopIteration(
                id=self.state.current_iteration,
                timestamp=str(datetime.now()),
                goal=self.state.inspiration_goal,
                brainstorming_output=current_brainstorm_output
            )
            self.state.history.append(iteration_record)
            self.state.save()
            
            # 3. Design (Stitch)
            self.state.current_status = f"Stitch is designing UI for Iteration {self.state.current_iteration}..."
            self.state.save()
            
            if not self.state.stitch_project_id:
                try:
                    self.state.stitch_project_id = self.stitch.create_project(self.state.project_name)
                    self.state.save()
                    self._update_env_file("STITCH_PROJECT_ID", self.state.stitch_project_id)
                except Exception as e:
                    logger.error(f"Failed to create Stitch project: {e}")
            
            design_success = False
            for attempt in range(3):
                try:
                    logger.info(f"Generating base design (Attempt {attempt+1}/3)...")
                    design_file, screen_id = self.stitch.generate_or_edit_screen(
                        description=self.state.inspiration_goal,
                        project_id=self.state.stitch_project_id or os.getenv("STITCH_PROJECT_ID", ""),
                        screen_id=self.state.stitch_screen_id
                    )
                    
                    if not design_file or not os.path.exists(design_file):
                        raise Exception("Stitch did not return a valid HTML design.")
                    
                    # Save base design immediately
                    design_src = os.path.abspath("app/design/reference.png")
                    ts = int(time.time())
                    if os.path.exists(design_src):
                        base_design_dest = f"viewer/public/artifacts/iter_{self.state.current_iteration}_base_design_{ts}.png"
                        shutil.copy(design_src, base_design_dest)
                        iteration_record.design_screenshot_path = f"artifacts/iter_{self.state.current_iteration}_base_design_{ts}.png"
                        self.state.save()
                    
                    # Design Review Stage: Generate Variants and Pick the Best
                    if screen_id:
                        self.state.current_status = f"Overseer is reviewing design variants..."
                        self.state.save()
                        logger.info("Generating and reviewing design variants...")
                        
                        try:
                            variants = self.stitch.generate_variants(
                                prompt="Explore distinct layouts, color palettes, and structural variations to find the optimal UI for the current goal.",
                                project_id=self.state.stitch_project_id,
                                screen_id=screen_id,
                                count=3
                            )
                        except Exception as var_e:
                            logger.warning(f"Variant generation failed: {var_e}. Proceeding with base design.")
                            variants = []
                        
                        if variants and hasattr(self, 'model'):
                            iteration_record.design_variants_paths = []
                            valid_variants = []
                            ts = int(time.time())
                            for idx, var in enumerate(variants):
                                if not var.get("img_bytes"):
                                    continue
                                var_dest = f"viewer/public/artifacts/iter_{self.state.current_iteration}_variant_{idx+1}_{ts}.png"
                                with open(var_dest, "wb") as f:
                                    f.write(var["img_bytes"])
                                iteration_record.design_variants_paths.append(f"artifacts/iter_{self.state.current_iteration}_variant_{idx+1}_{ts}.png")
                                valid_variants.append(var)
                                
                            self.state.save()
                            
                            if valid_variants:
                                prompt = [
                                    f"You are the Overseer. Your goal is: '{self.state.inspiration_goal}'.\n",
                                    "Here is the base design and some design variants generated for this goal. Please evaluate all of them for layout quality, usability, and aesthetic appeal."
                                ]
                                content = []
                                
                                # Include Base Design as option 1
                                try:
                                    with open(os.path.abspath("app/design/reference.png"), "rb") as f:
                                        base_img_bytes = f.read()
                                        prompt.append("Image 1: Base Design")
                                        content.append({"mime_type": "image/png", "data": base_img_bytes})
                                except Exception as e:
                                    logger.warning(f"Failed to load base design for critique: {e}")

                                # Include Variants as subsequent options
                                for idx, var in enumerate(valid_variants):
                                    img_num = idx + 2 if "Image 1: Base Design" in prompt else idx + 1
                                    prompt.append(f"Image {img_num}: Variant {idx+1}")
                                    content.append({"mime_type": "image/png", "data": var["img_bytes"]})
                                    
                                max_idx = len(valid_variants) + 1 if "Image 1: Base Design" in prompt else len(valid_variants)
                                prompt.append(f"Critique all designs briefly, rank them, and pick the absolute best one. Output ONLY the integer index (1 to {max_idx}) of the best design on the final line.")
                                
                                review_response = self.model.generate_content([*prompt, *content])
                                review_text = review_response.text.strip()
                                logger.info(f"Design Review Critique:\n{review_text}")
                                
                                iteration_record.design_review_critique = review_text
                                self.state.save()
                                
                                try:
                                    lines = [l.strip() for l in review_text.split("\n") if l.strip()]
                                    best_idx_raw = int(''.join(filter(str.isdigit, lines[-1])))
                                    
                                    if "Image 1: Base Design" in prompt:
                                        if best_idx_raw == 1:
                                            logger.info("Selected Base Design (No variant overwrite needed)")
                                            screen_id = self.state.stitch_screen_id
                                            # No file overwrite needed
                                        else:
                                            # Offset by 2 (e.g., Image 2 -> Variant index 0)
                                            var_idx = max(0, min(len(valid_variants) - 1, best_idx_raw - 2))
                                            logger.info(f"Selected Variant {var_idx + 1}")
                                            chosen_variant = valid_variants[var_idx]
                                            screen_id = chosen_variant["screen_id"]
                                            
                                            if chosen_variant.get("html_content"):
                                                with open(design_file, "w", encoding="utf-8") as f:
                                                    f.write(chosen_variant["html_content"])
                                                
                                            if chosen_variant.get("img_bytes"):
                                                ref_img_path = os.path.join("app", "design", "reference.png")
                                                with open(ref_img_path, "wb") as f:
                                                    f.write(chosen_variant["img_bytes"])
                                    else:
                                        # Fallback if base design failed to load
                                        var_idx = max(0, min(len(valid_variants) - 1, best_idx_raw - 1))
                                        logger.info(f"Selected Variant {var_idx + 1}")
                                        chosen_variant = valid_variants[var_idx]
                                        screen_id = chosen_variant["screen_id"]
                                        
                                        if chosen_variant.get("html_content"):
                                            with open(design_file, "w", encoding="utf-8") as f:
                                                f.write(chosen_variant["html_content"])
                                            
                                        if chosen_variant.get("img_bytes"):
                                            ref_img_path = os.path.join("app", "design", "reference.png")
                                            with open(ref_img_path, "wb") as f:
                                                f.write(chosen_variant["img_bytes"])
                                        
                                except Exception as e:
                                    logger.warning(f"Failed to parse variant selection, defaulting to base screen: {e}")
                            else:
                                logger.warning("No valid variant images found. Proceeding with base design.")
                        
                        self.state.stitch_screen_id = screen_id
                        self.state.save()
                        design_success = True
                        break # Break out of retry loop
                except Exception as e:
                    logger.error(f"Failed to generate screen or variants: {e}")
                    time.sleep(5)
                    
            if not design_success:
                logger.error("Failed to generate design after 3 attempts. Aborting iteration and returning to main.")
                self.git.checkout_branch("main")
                self.git._run(["git", "reset", "--hard", "origin/main"], cwd="app")
                self.git._run(["git", "clean", "-fd"], cwd="app")
                continue # Skip to next loop iteration
                
            self.git.commit(f"design: stitch output for iter {self.state.current_iteration}")
            
            # Inner Refinement Loop
            max_attempts = 3
            current_attempt = 1
            last_critique = ""
            happiness = 0
            attempt_branch = branch_name

            while current_attempt <= max_attempts:
                logger.info(f"--- Attempt {current_attempt}/{max_attempts} for Iteration {self.state.current_iteration} ---")
                
                self.state.current_status = f"Jules is coding (Iteration {self.state.current_iteration}, Attempt {current_attempt})..."
                self.state.save()
                
                # Use a unique branch per attempt to avoid Jules caching old commits
                attempt_branch = f"{branch_name}-att{current_attempt}"
                try:
                    self.git._run(["git", "checkout", "-b", attempt_branch], cwd="app")
                except:
                    self.git._run(["git", "checkout", attempt_branch], cwd="app")

                # 4. Build (Jules)
                if current_attempt == 1:
                    task_prompt = f"Implement the design for '{self.state.inspiration_goal}' using React, Vite, and Tailwind CSS. The design files (HTML and reference screenshot) are in app/design. Use strict TypeScript. Return a patch that updates app/src/App.tsx or other relevant files."
                else:
                    # Compile previous critiques
                    past_critiques = ""
                    for past_att in iteration_record.attempts:
                        past_critiques += f"\nAttempt {past_att.attempt_number} (Score: {past_att.score}/10) Critique:\n{past_att.critique}\n"
                        
                    task_prompt = f"Refine the implementation of '{self.state.inspiration_goal}'. Please review the feedback from your previous attempts and fix the remaining issues noted by the Overseer:\n{past_critiques}\n\nThe reference design files remain in app/design. Focus on architectural accuracy, visual fidelity, and ensuring the application compiles successfully."

                self.git.push_branch(attempt_branch)
                owner, repo_name = self._get_repo_info()

                try:
                    self.jules.run_task(task_prompt, owner, repo_name, attempt_branch)
                    self.git.commit(f"feat: jules implementation attempt {current_attempt}")
                    # Push so next attempt has the latest code
                    self.git.push_branch(attempt_branch)
                except Exception as e:
                    logger.error(f"Build failed: {e}")
                    
                # Save patch to artifacts if it exists
                patch_src = "app/jules.patch"
                patch_dest_rel = None
                if os.path.exists(patch_src):
                    ts = int(time.time())
                    patch_dest = f"viewer/public/artifacts/iter_{self.state.current_iteration}_attempt_{current_attempt}_{ts}.patch"
                    shutil.copy(patch_src, patch_dest)
                    patch_dest_rel = f"artifacts/iter_{self.state.current_iteration}_attempt_{current_attempt}_{ts}.patch"

                self.state.current_status = f"Overseer is evaluating (Iteration {self.state.current_iteration}, Attempt {current_attempt})..."
                self.state.save()
                
                # 4.5. Verify Build
                logger.info("Verifying Build Integrity...")
                build_success = True
                build_error = ""
                try:
                    subprocess.run(["npm", "run", "build"], cwd="app", check=True, capture_output=True, text=True)
                except subprocess.CalledProcessError as e:
                    build_success = False
                    build_error = e.stderr or e.stdout
                    logger.warning(f"Build failed:\n{build_error[:500]}")

                if not build_success:
                    happiness = 0
                    last_critique = f"The application failed to compile. Do not return a patch with compilation errors. Build error:\n{build_error[:1000]}"
                    app_screenshot = None
                else:
                    # 5. Evaluate
                    happiness, last_critique, app_screenshot = self.evaluate_happiness()
                    logger.info(f"Visual Happiness Score: {happiness}/10")
                
                # 5.5 Evaluate Architecture if visually happy
                if happiness >= 8:
                    arch_score, arch_critique = self.evaluate_architecture(branch_name)
                    iteration_record.architectural_critique = arch_critique
                    if arch_score < 8:
                        logger.warning(f"Architecture failed with score {arch_score}/10. Kicking back to Jules.")
                        happiness = arch_score
                        last_critique = f"Visuals are good, but architecture needs work:\n\n{arch_critique}"
                
                app_screenshot_path = None
                if app_screenshot:
                    ts = int(time.time())
                    app_screenshot_path = f"artifacts/iter_{self.state.current_iteration}_attempt_{current_attempt}_app_{ts}.png"
                    with open(f"viewer/public/{app_screenshot_path}", "wb") as f:
                        f.write(app_screenshot)
                
                # 6. Save Attempt Data
                attempt_record = AttemptRecord(
                    attempt_number=current_attempt,
                    prompt_used=task_prompt,
                    app_screenshot_path=app_screenshot_path,
                    jules_patch_path=patch_dest_rel,
                    score=happiness,
                    critique=last_critique
                )
                iteration_record.attempts.append(attempt_record)
                iteration_record.happiness_score = happiness
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
                    self.git._run(["git", "merge", attempt_branch], cwd="app")
                    self.git.push_branch("main")
                    
                    self.state.current_status = "Brainstorming next iteration..."
                    self.state.save()
                    
                    logger.info("Brainstorming next addition to keep the build going...")
                    next_prompt = f"""
We just successfully implemented: '{self.state.inspiration_goal}'. 
Look at the attached screenshot of the current application. Based on its visual layout and current state, your task is to determine the absolute best next step for this application.

1. Generate exactly 3 distinct, highly creative, and logical new features or visual improvements we should add to this UI next.
2. For each idea, briefly weigh the pros and cons of implementing it based on how well it fits the current visual layout and how much value it adds.
3. Rank the 3 ideas from 1st (best, most logical next step) to 3rd.
4. Output the 1st ranked idea as a detailed, comprehensive paragraph describing exactly how the new feature should look and function.

Format your final choice clearly starting with "SELECTED CONCEPT:" so it can be reliably parsed.
"""
                    next_idea = self.think(next_prompt, app_screenshot)
                    logger.info(f"Iterative Brainstorming Output:\n{next_idea}")
                    current_brainstorm_output = next_idea
                    
                    if "SELECTED CONCEPT:" in next_idea:
                        self.state.inspiration_goal = next_idea.split("SELECTED CONCEPT:")[1].strip()
                    else:
                        lines = [l.strip() for l in next_idea.strip().split("\n") if l.strip()]
                        self.state.inspiration_goal = lines[-1] if lines else "Add a settings panel."
                        
                    logger.info(f"Next Idea: {self.state.inspiration_goal}")
                    self.state.save()
                    
                except Exception as e:
                    logger.error(f"Merge to main failed: {e}. Resetting main.")
                    self.git._run(["git", "reset", "--hard", "origin/main"], cwd="app")
            else:
                logger.info("Max attempts reached without achieving happiness. Abandoning iteration and returning to main.")
                self.git.checkout_branch("main")
                self.git._run(["git", "reset", "--hard", "origin/main"], cwd="app")
                self.git._run(["git", "clean", "-fd"], cwd="app")
            
            logger.info("Waiting 10 seconds before next loop...")
            self.state.current_status = "Idle - Waiting for next loop..."
            self.state.save()
            time.sleep(10)
