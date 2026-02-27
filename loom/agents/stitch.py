import os
import json
import logging
import requests
from typing import Optional, Tuple
from pathlib import Path
from loom.agents.base import AgentProxy
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log

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

    def _call_mcp(self, method_name: str, arguments: dict, project_id: Optional[str] = None) -> dict:
        api_key = os.getenv("STITCH_API_KEY")
        headers = {"Content-Type": "application/json"}
        
        if api_key:
            headers["X-Goog-Api-Key"] = api_key
        else:
            access_token = self._get_access_token()
            headers["Authorization"] = f"Bearer {access_token}"
            # Some tools like list_projects don't require X-Goog-User-Project
            if project_id:
                headers["X-Goog-User-Project"] = project_id

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": method_name,
                "arguments": arguments
            },
            "id": 1
        }
        
        response = requests.post(self.BASE_URL, json=payload, headers=headers, timeout=600)
        
        if not response.ok:
            logger.error(f"Stitch API Error ({response.status_code}): {response.text}")
            raise Exception(f"Stitch API request failed: {response.status_code}")

        data = response.json()
        if "error" in data:
            raise Exception(f"Stitch API Error: {data['error']}")
        return data

    def create_project(self, title: str) -> str:
        logger.info(f"Creating new Stitch project: {title}")
        data = self._call_mcp("create_project", {"title": title})
        
        result = data.get("result", {})
        for block in result.get("content", []):
            if block.get("type") == "text":
                try:
                    inner = json.loads(block.get("text", ""))
                    # Returns e.g. "projects/4044680601076201931"
                    name = inner.get("name", "")
                    if name.startswith("projects/"):
                        pid = name.split("/")[1]
                        logger.info(f"New project created: {pid}")
                        return pid
                except json.JSONDecodeError:
                    pass
        raise Exception("Failed to parse project creation response")

    def create_design_system(self, project_id: str, color_mode: str, font: str, roundness: str, preset: str, description: str = "") -> str:
        logger.info(f"Creating Design System for project {project_id}...")
        arguments = {
            "projectId": project_id,
            "designSystem": {
                "theme": {
                    "colorMode": color_mode,
                    "font": font,
                    "roundness": roundness,
                    "preset": preset,
                    "description": description
                }
            }
        }
        
        data = self._call_mcp("create_design_system", arguments, project_id)
        result = data.get("result", {})
        for block in result.get("content", []):
            if block.get("type") == "text":
                try:
                    inner = json.loads(block.get("text", ""))
                    name = inner.get("name", "")
                    if name.startswith("assets/"):
                        asset_id = name.split("/")[1]
                        logger.info(f"New design system created: {asset_id}")
                        return asset_id
                except json.JSONDecodeError:
                    pass
        raise Exception("Failed to parse design system creation response")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
    def generate_or_edit_screen(self, description: str, project_id: str, screen_id: Optional[str] = None) -> list:
        """
        Returns a list of screen dictionaries: [{ "html": str, "images": [bytes], "screen_id": str }]
        """
        import uuid
        nonce = uuid.uuid4().hex[:8]
        enforced_description = f"{description}\n\n[Request ID: {nonce}]\n\nCRITICAL: You must generate a complete UI design based on this prompt. Do NOT ask any follow-up questions or request clarification."
        
        if screen_id:
            logger.info(f"Editing existing screen {screen_id} in project {project_id} using GEMINI_3_PRO: {description}")
            method = "edit_screens"
            arguments = {
                "projectId": project_id,
                "selectedScreenIds": [screen_id],
                "prompt": enforced_description,
                "modelId": "GEMINI_3_PRO",
                "deviceType": "DESKTOP"
            }
        else:
            logger.info(f"Generating new screen in project {project_id} using GEMINI_3_PRO: {description}")
            method = "generate_screen_from_text"
            arguments = {
                "projectId": project_id,
                "prompt": enforced_description,
                "modelId": "GEMINI_3_PRO",
                "deviceType": "DESKTOP"
            }
            
        logger.info(f"Calling Stitch API (method={method}, timeout=300s)...")
        data = self._call_mcp(method, arguments, project_id)
        
        result = data.get("result", {})
        content_blocks = result.get("content", [])
        all_screens = []
        
        for block in content_blocks:
            if block.get("type") == "text":
                raw_text = block.get("text", "")
                if "The service is currently unavailable" in raw_text:
                     raise Exception("Stitch Service Unavailable")
                try:
                    inner_json = json.loads(raw_text)
                    
                    output_components = inner_json.get("outputComponents", [{}])
                    if "text" in output_components[0] and "design" not in output_components[0]:
                        stitch_response = output_components[0]["text"]
                        raise Exception(f"Stitch asked a question or failed to generate UI: {stitch_response}")
                    screens = output_components[0].get("design", {}).get("screens", [])
                    
                    for screen in screens:
                        screen_data = {
                            "screen_id": screen.get("name", "").split("/")[-1] or screen_id,
                            "html": "",
                            "images": []
                        }
                        
                        # Collect Primary Screenshot
                        if "screenshot" in screen:
                            img_url = screen["screenshot"].get("downloadUrl")
                            if img_url:
                                img_resp = requests.get(img_url, timeout=30)
                                if img_resp.ok:
                                    screen_data["images"].append(img_resp.content)
                        
                        # Collect Additional Screenshots
                        for add_img in screen.get("additionalScreenshots", []):
                            add_url = add_img.get("downloadUrl")
                            if add_url:
                                add_resp = requests.get(add_url, timeout=30)
                                if add_resp.ok:
                                    screen_data["images"].append(add_resp.content)

                        # Download HTML
                        if "htmlCode" in screen:
                            download_url = screen["htmlCode"].get("downloadUrl")
                            if download_url:
                                html_resp = requests.get(download_url, timeout=30)
                                if html_resp.ok:
                                    screen_data["html"] = html_resp.text
                        
                        if screen_data["html"] or screen_data["images"]:
                            all_screens.append(screen_data)
                except json.JSONDecodeError:
                    pass

        if not all_screens:
            raise Exception("No design content generated.")

        return all_screens

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
    def generate_variants(self, prompt: str, project_id: str, screen_id: str, count: int = 3, creative_range: str = "EXPLORE", aspects: list = None) -> list:
        if aspects is None: aspects = ["LAYOUT"]
        logger.info(f"Generating {count} variants for screen {screen_id} in project {project_id}: {prompt}")
        method = "generate_variants"
        arguments = {
            "projectId": project_id,
            "selectedScreenIds": [screen_id],
            "prompt": prompt,
            "modelId": "GEMINI_3_PRO",
            "deviceType": "DESKTOP",
            "variantOptions": {
                "variantCount": count,
                "creativeRange": creative_range,
                "aspects": aspects
            }
        }
        
        data = self._call_mcp(method, arguments, project_id)
        result = data.get("result", {})
        content_blocks = result.get("content", [])
        variants = []
        
        for block in content_blocks:
            if block.get("type") == "text":
                raw_text = block.get("text", "")
                try:
                    inner_json = json.loads(raw_text)
                    screens = inner_json.get("outputComponents", [{}])[0].get("design", {}).get("screens", [])
                    
                    for idx, screen in enumerate(screens):
                        variant_data = {
                            "screen_id": screen.get("name", "").split("/")[-1] or f"var_{idx}",
                            "html_content": "",
                            "images": [] # All images for this variant
                        }
                        
                        # Primary Screenshot
                        if "screenshot" in screen:
                            img_url = screen["screenshot"].get("downloadUrl")
                            if img_url:
                                img_resp = requests.get(img_url, timeout=30)
                                if img_resp.ok: variant_data["images"].append(img_resp.content)
                                    
                        # Additional Screenshots
                        for add_img in screen.get("additionalScreenshots", []):
                            add_url = add_img.get("downloadUrl")
                            if add_url:
                                add_resp = requests.get(add_url, timeout=30)
                                if add_resp.ok: variant_data["images"].append(add_resp.content)

                        if "htmlCode" in screen:
                            download_url = screen["htmlCode"].get("downloadUrl")
                            if download_url:
                                html_resp = requests.get(download_url, timeout=30)
                                if html_resp.ok: variant_data["html_content"] = html_resp.text
                                    
                        if variant_data["html_content"] or variant_data["images"]:
                            variants.append(variant_data)
                except json.JSONDecodeError:
                    pass
        
        return variants
