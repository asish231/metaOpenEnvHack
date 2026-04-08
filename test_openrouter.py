import os
from openai import OpenAI
from dotenv import load_dotenv

# Load variables from .env
load_dotenv()

def test_openrouter():
    api_key = os.environ.get("OPENROUTER_API_KEY")
    base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    model_name = os.environ.get("OPENROUTER_MODEL_NAME", "openai/gpt-oss-120b:free")
    
    print(f"Testing OpenRouter with model: {model_name}...")
    print(f"Base URL: {base_url}")
    
    if not api_key or api_key == "YOUR_OPENROUTER_KEY_HERE":
        print("Error: OPENROUTER_API_KEY environment variable is not set to a valid key in .env.")
        print("Please edit .env to add your actual OpenRouter API Key.")
        return

    client = OpenAI(
        api_key=api_key,
        base_url=base_url
    )

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "user", "content": "What is 2+2? Reply with just the number."}
            ],
            max_tokens=50,
            temperature=0.1
        )
        
        reply = response.choices[0].message.content
        print("\n--- SUCCESS ---")
        print(f"API Connected successfully! Response received:\n{reply}")
        
    except Exception as e:
        print("\n--- FAILED ---")
        print("The query to OpenRouter failed. Here are the error details:")
        print(str(e))

if __name__ == "__main__":
    test_openrouter()
