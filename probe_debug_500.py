import google.generativeai as genai
import os
import time
from dotenv import load_dotenv
load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

models_to_test = [
    'gemini-3.1-pro-preview',
    'gemini-3-pro-preview',
    'gemini-3-flash-preview'
]

for model_name in models_to_test:
    print(f"Testing {model_name}...")
    try:
        model = genai.GenerativeModel(model_name)
        start_time = time.time()
        response = model.generate_content("Say 'online'", request_options={"timeout": 30})
        duration = time.time() - start_time
        print(f"  SUCCESS: {response.text.strip()} (took {duration:.2f}s)")
    except Exception as e:
        print(f"  FAILED: {e}")
    print("-" * 20)
