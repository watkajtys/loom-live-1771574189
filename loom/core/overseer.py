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
        logger.info("Evaluating architectural best practices...")
        try:
            diff_output = self.git._run(["git", "diff", f"main...{branch_name}", "--", "src/", "package.json"], cwd="app")
            
            if not diff_output.strip():
                return 10, "No code changes detected to review."
                
            prompt = f"""
You are an expert Principal Software Engineer acting as the Architectural Reviewer for Project Loom.
The application is built using React, Vite, and Tailwind CSS.
App Identity & Core Architecture: {self.state.app_meta}

Please review the following git diff containing the changes made in this iteration.

Evaluate the changes based on:
1. Technical best practices (React hooks, state management, pure functions).
2. Modularity and separation of concerns (are components getting too large?).
3. Maintainability and readability.
4. Alignment with the App Identity/Architecture defined above.
5. Any potential performance bottlenecks (unnecessary re-renders, complex layout thrashing).

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

    def evaluate_happiness(self, target_route: str = "/") -> tuple[int, str, bytes]:
        score = 10 
        critique = "No critique."
        app_screenshot = None
        try:
            self.phoenix.spawn()
            self.phoenix.wait_for_ready()
            logger.info(f"Phoenix Server is up. App is running. Verifying route {target_route} with Vision...")
            
            try:
                # Navigate to the specific route for this iteration
                app_screenshot, console_logs = self._take_screenshot(f"http://localhost:{self.phoenix.port}{target_route}", return_logs=True)
                design_path = os.path.abspath("app/design/latest_design.html")
                design_screenshot = self._take_screenshot(design_path, wait_ms=500) if os.path.exists(design_path) else None
                
                if hasattr(self, 'model'):
                    prompt = [
                        f"You are the Overseer. Your goal was to implement: '{self.state.inspiration_goal}'.\n",
                        f"App Identity (Meta): {self.state.app_meta}\n",
                        f"Target Route: {target_route}\n",
                        "The first image is the actual React app running."
                    ]
                    content = [{"mime_type": "image/png", "data": app_screenshot}]
                    
                    if design_screenshot:
                        prompt.append("The second image is the target design we are trying to achieve.")
                        content.append({"mime_type": "image/png", "data": design_screenshot})
                        
                    prompt.append("Score how well the actual app matches the target design and the core App Identity from 0 to 10. Pay special attention to whether the new feature was integrated correctly without destroying existing UI. Output ONLY the integer score on the first line, followed by a brief critique on the next lines.")
                    
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
        # Recover target route from history if resuming
        current_target_route = self.state.history[-1].target_route if self.state.history else "/"
        
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

1. Generate exactly 3 highly distinct, creative ideas for a web application. Ensure the ideas are functionally clear and buildable.
2. For each idea, briefly weigh its potential for a stunning, polished UI and clear interactive functionality.
3. Rank the 3 ideas. Rank them based on the best balance of VISUAL APPEAL and PRACTICAL UTILITY. 

4. Output your choice using the following structured tags:

[SELECTED CONCEPT]
A detailed paragraph describing the app's architecture, aesthetic, and core functionality. 

[TARGET_ROUTE]
The URL path where the core feature will live (e.g. /)

[APP_META]
A markdown-formatted summary defining the App Name, Core Value Proposition, Global Color Palette (Tailwind colors), and Typography.
"""
                raw_response = self.think(prompt)
                logger.info(f"Brainstorming Output:\n{raw_response}")
                current_brainstorm_output = raw_response
                
                if "[SELECTED CONCEPT]" in raw_response:
                    self.state.inspiration_goal = raw_response.split("[SELECTED CONCEPT]")[1].split("[")[0].strip()
                else:
                    self.state.inspiration_goal = raw_response.strip().split("\n")[-1]

                if "[TARGET_ROUTE]" in raw_response:
                    current_target_route = raw_response.split("[TARGET_ROUTE]")[1].split("[")[0].strip()
                
                if "[APP_META]" in raw_response:
                    meta_part = raw_response.split("[APP_META]")[1]
                    if "[" in meta_part:
                        self.state.app_meta = meta_part.split("[")[0].strip()
                    else:
                        self.state.app_meta = meta_part.strip()
                        
                    # Write meta to disk in the app repo
                    os.makedirs("app", exist_ok=True)
                    with open("app/APP_META.md", "w", encoding="utf-8") as f:
                        f.write(self.state.app_meta)
                    
                    try:
                        self.git._run(["git", "add", "APP_META.md"], cwd="app")
                        self.git.commit("chore: initialize app meta memory")
                    except Exception as e:
                        logger.warning(f"Failed to commit APP_META.md: {e}")
                    
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
                target_route=current_target_route,
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
                    
                    # Context-aware design prompt
                    design_prompt = f"Application Identity: {self.state.app_meta}\n\nTask: {self.state.inspiration_goal}\n\nTarget Route: {current_target_route}"
                    
                    design_file, screen_id = self.stitch.generate_or_edit_screen(
                        description=design_prompt,
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
                                prompt=f"Explore distinct layouts for this concept: {self.state.inspiration_goal}. Preserve the theme defined in: {self.state.app_meta}",
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
                                    f"You are the Overseer. Goal: '{self.state.inspiration_goal}'. Meta: {self.state.app_meta}\n",
                                    "Pick the most stunning design that aligns with the meta. Output ONLY the integer index on the final line."
                                ]
                                content = []
                                try:
                                    with open(os.path.abspath("app/design/reference.png"), "rb") as f:
                                        base_img_bytes = f.read()
                                        prompt.append("Image 1: Base Design")
                                        content.append({"mime_type": "image/png", "data": base_img_bytes})
                                except: pass

                                for idx, var in enumerate(valid_variants):
                                    img_num = idx + 2 if "Image 1: Base Design" in prompt else idx + 1
                                    prompt.append(f"Image {img_num}: Variant {idx+1}")
                                    content.append({"mime_type": "image/png", "data": var["img_bytes"]})
                                    
                                review_response = self.model.generate_content([*prompt, *content])
                                review_text = review_response.text.strip()
                                iteration_record.design_review_critique = review_text
                                self.state.save()
                                
                                try:
                                    lines = [l.strip() for l in review_text.split("\n") if l.strip()]
                                    best_idx_raw = int(''.join(filter(str.isdigit, lines[-1])))
                                    if "Image 1: Base Design" in prompt and best_idx_raw == 1:
                                        iteration_record.chosen_design_path = iteration_record.design_screenshot_path
                                    else:
                                        var_idx = max(0, min(len(valid_variants) - 1, best_idx_raw - 2 if "Image 1: Base Design" in prompt else best_idx_raw - 1))
                                        chosen_variant = valid_variants[var_idx]
                                        screen_id = chosen_variant["screen_id"]
                                        iteration_record.chosen_design_path = iteration_record.design_variants_paths[var_idx]
                                        if chosen_variant.get("html_content"):
                                            with open(design_file, "w", encoding="utf-8") as f:
                                                f.write(chosen_variant["html_content"])
                                        if chosen_variant.get("img_bytes"):
                                            with open(os.path.join("app", "design", "reference.png"), "wb") as f:
                                                f.write(chosen_variant["img_bytes"])
                                except Exception as e:
                                    logger.warning(f"Failed to parse variant selection: {e}")
                            
                        self.state.stitch_screen_id = screen_id
                        self.state.save()
                        design_success = True
                        break 
                except Exception as e:
                    logger.error(f"Failed to generate screen or variants: {e}")
                    time.sleep(5)
                    
            if not design_success:
                logger.error("Failed to generate design after 3 attempts. Aborting iteration.")
                self.git.checkout_branch("main")
                continue 
                
            self.git.commit(f"design: stitch output for iter {self.state.current_iteration}")
            
            # Inner Refinement Loop
            max_attempts = 50
            current_attempt = 1
            last_critique = ""
            happiness = 0
            attempt_branch = branch_name

            while current_attempt <= max_attempts:
                logger.info(f"--- Attempt {current_attempt}/{max_attempts} for Iteration {self.state.current_iteration} ---")
                self.state.current_status = f"Jules is coding (Iteration {self.state.current_iteration}, Attempt {current_attempt})..."
                self.state.save()
                
                attempt_branch = f"{branch_name}-att{current_attempt}"
                try:
                    self.git._run(["git", "checkout", "-b", attempt_branch], cwd="app")
                except:
                    self.git._run(["git", "checkout", attempt_branch], cwd="app")

                # 4. Build (Jules)
                if current_attempt == 1:
                    task_prompt = f"""
Implement the design for '{self.state.inspiration_goal}'.
App Identity: {self.state.app_meta}
Target Route: {current_target_route}

The design files are in app/design. 
CRITICAL: Integrate this new feature into the existing application. 
If '{current_target_route}' is a new route, you MUST set up React Router (using react-router-dom) without breaking the existing pages.
Ensure the final app compiles and matches the design.
"""
                else:
                    past_critiques = ""
                    if iteration_record.attempts:
                        last_att = iteration_record.attempts[-1]
                        past_critiques += f"\nPrevious Attempt {last_att.attempt_number} (Score: {last_att.score}/10) Critique:\n{last_att.critique}\n"
                    task_prompt = f"Refine the implementation. Meta: {self.state.app_meta}. Route: {current_target_route}. Feedback: {past_critiques}"

                self.git.push_branch(attempt_branch)
                owner, repo_name = self._get_repo_info()
                self.state.active_jules_prompt = task_prompt
                self.state.save()

                def update_jules_state(action: str, url: str):
                    self.state.active_jules_action = action
                    self.state.active_jules_url = url
                    self.state.save()

                try:
                    self.jules.run_task(task_prompt, owner, repo_name, attempt_branch, activity_callback=update_jules_state)
                    self.git.commit(f"feat: jules implementation attempt {current_attempt}")
                    self.git.push_branch(attempt_branch)
                except Exception as e:
                    logger.error(f"Build failed: {e}")
                finally:
                    self.state.active_jules_prompt = None
                    self.state.active_jules_action = None
                    self.state.active_jules_url = None
                    self.state.save()
                    
                patch_src = "app/jules.patch"
                patch_dest_rel = None
                if os.path.exists(patch_src):
                    ts = int(time.time())
                    patch_dest = f"viewer/public/artifacts/iter_{self.state.current_iteration}_attempt_{current_attempt}_{ts}.patch"
                    shutil.copy(patch_src, patch_dest)
                    patch_dest_rel = f"artifacts/iter_{self.state.current_iteration}_attempt_{current_attempt}_{ts}.patch"

                self.state.current_status = f"Overseer is evaluating (Iteration {self.state.current_iteration}, Attempt {current_attempt})..."
                self.state.save()
                
                logger.info("Verifying Build Integrity...")   
                build_success = True
                build_error = ""
                try:
                    subprocess.run(["npm", "install", "--no-audit", "--no-fund"], cwd="app", check=True, capture_output=True, text=True, shell=True)
                    subprocess.run(["npm", "run", "build"], cwd="app", check=True, capture_output=True, text=True, shell=True)
                except subprocess.CalledProcessError as e:    
                    build_success = False
                    build_error = e.stderr or e.stdout        
                except Exception as e:
                    build_success = False
                    build_error = str(e)
                
                if not build_success:
                    happiness = 0
                    last_critique = f"The application failed to compile. Build error:\n{build_error[:1000]}"
                    app_screenshot = None
                else:
                    happiness, last_critique, app_screenshot = self.evaluate_happiness(target_route=current_target_route)
                    logger.info(f"Visual Happiness Score: {happiness}/10")
                
                if happiness >= 8:
                    arch_score, arch_critique = self.evaluate_architecture(branch_name)
                    iteration_record.architectural_critique = arch_critique
                    if arch_score < 8:
                        happiness = arch_score
                        last_critique = f"Visuals are good, but architecture needs work:\n\n{arch_critique}"
                
                app_screenshot_path = None
                if app_screenshot:
                    ts = int(time.time())
                    app_screenshot_path = f"artifacts/iter_{self.state.current_iteration}_attempt_{current_attempt}_app_{ts}.png"
                    with open(f"viewer/public/{app_screenshot_path}", "wb") as f:
                        f.write(app_screenshot)
                
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

            # 7. Final Decision for the Iteration
            if happiness >= 8:
                logger.info("Happiness achieved! Merging to main.")
                self.git.checkout_branch("main")
                try:
                    self.git._run(["git", "merge", attempt_branch], cwd="app")
                    self.git.push_branch("main")
                    
                    self.state.current_status = "Brainstorming next iteration..."
                    self.state.save()
                    
                    logger.info("Brainstorming next addition...")
                    
                    try:
                        src_tree = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", "HEAD", "src/"], cwd="app", text=True)
                    except Exception:
                        src_tree = "src/ tree unavailable."
                        
                    next_prompt = f"""
We just successfully implemented: '{self.state.inspiration_goal}' at route '{current_target_route}'. 
App Identity: {self.state.app_meta}

Current Codebase Files:
```text
{src_tree}
```

Look at the attached screenshot. Based on the meta, codebase, and current state, what is the best next step?

1. Generate 3 distinct new features or routes.
2. Output your choice using the structured tags:

[SELECTED CONCEPT]
Paragraph description...

[TARGET_ROUTE]
The URL path (existing or new) where this will be visible.

[APP_META]
Update the App Meta if you are adding new global systems or routes.
"""
                    next_idea = self.think(next_prompt, app_screenshot)
                    logger.info(f"Iterative Brainstorming Output:\n{next_idea}")
                    current_brainstorm_output = next_idea
                    
                    if "[SELECTED CONCEPT]" in next_idea:
                        self.state.inspiration_goal = next_idea.split("[SELECTED CONCEPT]")[1].split("[")[0].strip()
                    else:
                        self.state.inspiration_goal = next_idea.strip().split("\n")[-1]

                    if "[TARGET_ROUTE]" in next_idea:
                        current_target_route = next_idea.split("[TARGET_ROUTE]")[1].split("[")[0].strip()

                    if "[APP_META]" in next_idea:
                        meta_part = next_idea.split("[APP_META]")[1]
                        if "[" in meta_part:
                            self.state.app_meta = meta_part.split("[")[0].strip()
                        else:
                            self.state.app_meta = meta_part.strip()
                        
                        with open("app/APP_META.md", "w", encoding="utf-8") as f:
                            f.write(self.state.app_meta)
                    
                    self.state.save()
                    
                except Exception as e:
                    logger.error(f"Merge to main failed: {e}. Resetting main.")
                    self.git._run(["git", "reset", "--hard", "origin/main"], cwd="app")
            else:
                logger.info("Max attempts reached. Abandoning iteration.")
                self.git.checkout_branch("main")
                self.git._run(["git", "reset", "--hard", "origin/main"], cwd="app")
                self.git._run(["git", "clean", "-fd"], cwd="app")
            
            time.sleep(10)
