import httpx
import logging
import asyncio
from typing import Dict, Any, Optional
from app.config import settings

logger = logging.getLogger("llm_client")

class LLMClient:
    async def generate_analysis(self, prompt: str, system_prompt: str, api_key: Optional[str] = None) -> Optional[str]:
        """Send prompt to Ollama generation API with JSON formatting constraint and temperature=0.0."""
        # Always read latest settings in case they were updated via the settings UI
        url = f"{settings.ollama_url.rstrip('/')}/api/generate"
        model = settings.ollama_model
        retries = settings.ollama_retries
        timeout = settings.ollama_timeout

        payload = {
            "model": model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
            "format": "json",  # Force Ollama to return structured JSON
            "options": {
                "temperature": 0.0,  # Make output as deterministic as possible
                "seed": 42
            }
        }

        headers = {}
        token = api_key or settings.ollama_api_key
        if token:
            headers["Authorization"] = f"Bearer {token}"


        for attempt in range(1, retries + 1):
            try:
                logger.info(f"Ollama request (attempt {attempt}/{retries}) using model: {model} to: {url}")
                async with httpx.AsyncClient(timeout=float(timeout)) as client:
                    response = await client.post(url, json=payload, headers=headers)
                    response.raise_for_status()

                    result_json = response.json()
                    response_text = result_json.get("response", "")

                    if response_text:
                        return response_text
                    else:
                        logger.warning(f"Ollama returned empty response on attempt {attempt}")
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                logger.error(f"Error communicating with Ollama (attempt {attempt}/{retries}): {e}")
                if attempt == retries:
                    # Raise or return None
                    return None
                # Linear backoff before retry
                await asyncio.sleep(attempt * 2.0)
                
        return None

# Global instance of LLM client
llm_client = LLMClient()
