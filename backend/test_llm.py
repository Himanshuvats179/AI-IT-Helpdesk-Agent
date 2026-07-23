import asyncio
import os
import sys

# Add the backend app dir to python path
sys.path.insert(0, os.path.abspath("."))

from dotenv import load_dotenv
load_dotenv()

from app.config import get_settings
from app.llm.anthropic_provider import AnthropicProvider

async def main():
    settings = get_settings()
    print(f"Testing model: {settings.llm_model}")
    try:
        provider = AnthropicProvider(settings)
        response = await provider.create_message(
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=100
        )
        print("Success!")
        print(response.content)
    except Exception as e:
        print("Error occurred:")
        print(e)

if __name__ == "__main__":
    asyncio.run(main())
