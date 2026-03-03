import os
import json
import logging
import google.generativeai as genai
from google.api_core import exceptions
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from loom.agents.base import AgentProxy

logger = logging.getLogger("loom")

class MockJulesClient(AgentProxy):
    """
    Simulates the Jules Agent using Gemini Pro.
    Reads the Stitch HTML and the App File Structure, then generates React Code directly.
    """
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            logger.warning("GEMINI_API_KEY missing for MockJules. Code generation will fail.")
        else:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel('gemini-3.1-pro-preview')

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=(
            retry_if_exception_type(exceptions.DeadlineExceeded) |
            retry_if_exception_type(exceptions.ServiceUnavailable) |
            retry_if_exception_type(exceptions.InternalServerError) |
            retry_if_exception_type(exceptions.ResourceExhausted)
        ),
        reraise=True
    )
    def _generate_content_with_retry(self, content):
        """Helper to call Gemini with robust exponential backoff retries."""
        try:
            return self.model.generate_content(content)
        except Exception as e:
            logger.warning(f"Mock Jules Gemini call failed (attempting retry): {e}")
            raise e

    def run_task(self, prompt: str, repo_owner: str = None, repo_name: str = None, branch: str = None, activity_callback=None) -> str:
        logger.info(f"Tasking Mock Jules (Gemini): {prompt}")
        
        if activity_callback:
            activity_callback("Analyzing codebase...", "")

        # 1. Gather Context
        context = ""
        design_path = "app/design/latest_design.html"
        if os.path.exists(design_path):
            with open(design_path, "r", encoding="utf-8") as f:
                context += f"""
--- STITCH DESIGN HTML ---
{f.read()}
"""
        
        # Read key app files for context
        for fpath in ["app/src/App.tsx", "app/tailwind.config.js", "app/package.json", "app/APP_META.md"]:
            if os.path.exists(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        context += f"""
--- {fpath} ---
{f.read()}
"""
                except:
                    pass

        # 2. Construct Prompt
        full_prompt = f"""
You are an expert React Engineer. Your task is to implement a UI or logic based on the provided Design HTML and existing codebase.

System Constraints:
- Use React + Vite + Tailwind CSS.
- The project is in 'app/'.
- You MUST integrate your changes into the existing architecture.
- Ensure all imports are correct and types are handled (TypeScript).

Task: {prompt}

Context:
{context}

Output:
Return a JSON object with the file updates. Use the exact relative paths from the project root (e.g. "app/src/App.tsx").
Example:
{{
  "app/src/App.tsx": "import ...",
  "app/src/components/Button.tsx": "..."
}}
"""
        
        if activity_callback:
            activity_callback("Generating code...", "")

        # 3. Call LLM
        try:
            response = self._generate_content_with_retry(full_prompt)
            text = response.text
            
            # 4. Parse JSON
            # Remove markdown code blocks if present
            clean_text = text.replace("```json", "").replace("```", "").strip()
            files_to_write = json.loads(clean_text)
            
            if activity_callback:
                activity_callback(f"Writing {len(files_to_write)} files...", "")

            # 5. Apply Changes
            for fpath, content in files_to_write.items():
                logger.info(f"Writing file: {fpath}")
                # Ensure directory exists
                os.makedirs(os.path.dirname(fpath), exist_ok=True)
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(content)
            
            return "Code Implemented via Mock Jules"
            
        except Exception as e:
            logger.error(f"Mock Jules Coding Failed: {e}")
            raise
