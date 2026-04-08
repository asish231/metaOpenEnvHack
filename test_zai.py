import os
from openai import OpenAI
from dotenv import load_dotenv

# Load variables from .env
load_dotenv()

def test_zai():
    api_key = os.environ.get("ZAI_API_KEY")
    base_url = os.environ.get("API_BASE_URL", "https://api.z.ai/api/paas/v4/")
    model_name = os.environ.get("MODEL_NAME", "GLM-4.7-Flash")
    
    print(f"Testing Z.AI with model: {model_name}...")
    print(f"Base URL: {base_url}")
    
    if not api_key:
        print("Error: ZAI_API_KEY environment variable is not set in .env.")
        return

    # Use the OpenAI client (which is compatible with Z.AI's API format)
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
        print("The query to Z.AI failed. Here are the error details:")
        print(str(e))

if __name__ == "__main__":
    test_zai()
