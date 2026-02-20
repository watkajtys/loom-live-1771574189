import os
import json
import logging
import requests
from pathlib import Path
from loom.agents.base import AgentProxy

logger = logging.getLogger("loom")
DESIGN_DIR = Path("app/design")

class StitchClient(AgentProxy):
    """
    Direct client for the Stitch MCP HTTP API.
    Uses 'gcloud auth print-access-token' for authentication or API key.
    """
    BASE_URL = "https://stitch.googleapis.com/mcp"

    def _get_access_token(self) -> str:
        try:
            token = os.getenv("STITCH_ACCESS_TOKEN")
            if token:
                return token
            return self._run(["gcloud", "auth", "print-access-token"]).strip()
        except Exception as e:
            logger.error(f"Failed to get gcloud token: {e}")
            raise

    def generate_screen(self, description: str) -> str:
        logger.info(f"Tasking Stitch API: {description}")
        try:
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

            payload = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "generate_screen_from_text",
                    "arguments": {
                        "projectId": project_id,
                        "prompt": description
                    }
                },
                "id": 1
            }
            
            logger.info("Calling Stitch API (timeout=300s)...")
            response = requests.post(self.BASE_URL, json=payload, headers=headers, timeout=300)
            
            if not response.ok:
                logger.error(f"Stitch API Error ({response.status_code}): {response.text}")
                raise Exception(f"Stitch API request failed: {response.status_code}")

            data = response.json()
            if "error" in data:
                 raise Exception(f"Stitch API Error: {data['error']}")
            
            result = data.get("result", {})
            content_blocks = result.get("content", [])
            html_content = ""
            
            for block in content_blocks:
                if block.get("type") == "text":
                    raw_text = block.get("text", "")
                    if "The service is currently unavailable" in raw_text:
                         raise Exception("Stitch Service Unavailable")
                    try:
                        inner_json = json.loads(raw_text)
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
                raise Exception("No HTML content generated.")

            design_file = DESIGN_DIR / "latest_design.html"
            DESIGN_DIR.mkdir(parents=True, exist_ok=True)
            with open(design_file, "w", encoding="utf-8") as f:
                f.write(html_content)
                
            return str(design_file)
            
        except Exception as e:
            logger.error(f"Stitch Generation Failed: {e}. Using fallback.")
            design_file = DESIGN_DIR / "latest_design.html"
            DESIGN_DIR.mkdir(parents=True, exist_ok=True)
            with open(design_file, "w", encoding="utf-8") as f:
                f.write(f"""<!-- Fallback Design for: {description} -->
<div class='min-h-screen bg-slate-900 text-white flex items-center justify-center'>
  <div class='p-8 bg-slate-800 rounded-xl shadow-2xl border border-slate-700'>
    <h1 class='text-4xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-purple-500 mb-4'>Stitch Loom Fallback</h1>
    <p class='text-slate-400 mb-6'>Design generated for: {description}</p>
  </div>
</div>""")
            return str(design_file)
