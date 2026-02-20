import os
import requests
import json
import time

# Load env manually
api_key = None
project_id = None
if os.path.exists(".env"):
    with open(".env", "r") as f:
        for line in f:
            if line.startswith("STITCH_API_KEY="):
                api_key = line.strip().split("=", 1)[1]
            if line.startswith("STITCH_PROJECT_ID="):
                project_id = line.strip().split("=", 1)[1]

if not api_key or not project_id:
    print("Error: Missing keys in .env")
    exit(1)

url = "https://stitch.googleapis.com/mcp"
headers = {
    "Content-Type": "application/json",
    "X-Goog-Api-Key": api_key
}

prompt = "A futuristic dashboard with neon blue accents, featuring a large circular data visualization in the center and a sidebar with glowing icons."

# 1. Generate Screen
payload = {
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
        "name": "generate_screen_from_text",
        "arguments": {
            "projectId": project_id,
            "prompt": prompt
        }
    },
    "id": 1
}

print(f"Generating Screen for: '{prompt}'...")
print(f"Target Project: {project_id}")

try:
    start_time = time.time()
    response = requests.post(url, json=payload, headers=headers, timeout=300) # Increased timeout for generation
    elapsed = time.time() - start_time
    
    print(f"Status Code: {response.status_code} (took {elapsed:.2f}s)")
    
    if response.status_code == 200:
        data = response.json()
        
        # Check for error in JSON-RPC response
        if "error" in data:
            print(f"JSON-RPC Error: {json.dumps(data['error'], indent=2)}")
        else:
            print("Generation Successful!")
            result = data.get("result", {})
            content = result.get("content", [])
            
            # Look for text content (which should contain the success message or HTML)
            found_content = False
            for block in content:
                if block.get("type") == "text":
                    text = block.get("text", "")
                    try:
                        # The text block contains stringified JSON
                        inner_json = json.loads(text)
                        screens = inner_json.get("outputComponents", [{}])[0].get("design", {}).get("screens", [])
                        
                        print(f"\n--- Analysis: Found {len(screens)} Screen(s) ---")
                        for i, screen in enumerate(screens):
                            has_html = "htmlCode" in screen
                            has_screenshot = "screenshot" in screen
                            print(f"Screen {i+1}: HTML={has_html}, Screenshot={has_screenshot}")
                            
                            if has_html:
                                html_url = screen["htmlCode"].get("downloadUrl", "No URL")
                                print(f"  -> HTML Download URL: {html_url}")
                                # In a real scenario, we would fetch this URL to get the code
                    except json.JSONDecodeError:
                         print("\n--- Raw Text Content (Not JSON) ---")
                         print(text[:500])

                    found_content = True
            
            if not found_content:
                print("Warning: No text content found in result.")
                print(json.dumps(data, indent=2))
                
    else:
        print(f"HTTP Error: {response.text}")

except Exception as e:
    print(f"Exception: {e}")
