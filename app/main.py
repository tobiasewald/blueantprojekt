import os
import yaml
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Header, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import settings, CONFIG_PATH, PROMPTS_PATH
from app.blueant_client import blueant_client, BlueAntAPIError
from app.analysis_service import analysis_service

app = FastAPI(
    title="Blue Ant AI Core & Prompt-Management Engine API",
    description="AP2 Backend service for Blue Ant project data analysis using Ollama LLMs",
    version="1.0.0"
)

# Enable CORS for the dashboard frontend (AP3) to connect easily
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
@app.get("/dashboard")
async def read_index():
    """Serve the AP3 Single Page Dashboard."""
    return FileResponse("static/index.html")


# Pydantic models for configuration and prompt updates
class PromptsUpdate(BaseModel):
    system_prompt: str
    project_analysis_prompt: str
    portfolio_analysis_prompt: str

class BlueAntConfigUpdate(BaseModel):
    url: str
    cache_ttl: int

class OllamaConfigUpdate(BaseModel):
    url: str
    model: str
    retries: int
    timeout: int

class FullConfigUpdate(BaseModel):
    blueant: BlueAntConfigUpdate
    ollama: OllamaConfigUpdate

# Dependency to extract Blue Ant API token from request headers or query params
def get_blueant_token(
    authorization: Optional[str] = Header(None),
    x_blueant_api_key: Optional[str] = Header(None),
    api_key: Optional[str] = Query(None)
) -> Optional[str]:
    # 1. Check custom header X-Blueant-API-Key
    if x_blueant_api_key:
        return x_blueant_api_key
    # 2. Check standard Authorization header (Bearer token)
    if authorization:
        if authorization.startswith("Bearer "):
            return authorization[7:]
        return authorization
    # 3. Check query param api_key
    if api_key:
        return api_key
    # 4. Fallback to settings
    if settings.blueant_api_key:
        return settings.blueant_api_key
    
    # Do not raise exception here, let the client functions report error if token is missing
    return None

# Dependency to extract Ollama API token from custom header
def get_ollama_token(
    x_ollama_api_key: Optional[str] = Header(None)
) -> Optional[str]:
    if x_ollama_api_key:
        return x_ollama_api_key
    if settings.ollama_api_key:
        return settings.ollama_api_key
    return None

@app.get("/health")
@app.get("/api/health")
async def health_check():
    """Health check endpoint to verify backend status."""
    return {"status": "healthy", "service": "AP2: AI Core & Prompt-Management Engine"}

@app.get("/api/portfolios")
async def get_portfolios(token: Optional[str] = Depends(get_blueant_token)):
    """Fetch raw list of all portfolios from Blue Ant."""
    if not token:
        raise HTTPException(status_code=401, detail="Missing Blue Ant API key. Please provide it in the headers or query.")
    try:
        portfolios = await blueant_client.get_portfolios(api_key=token)
    except BlueAntAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
    return {"portfolios": portfolios}

@app.get("/api/portfolio/{portfolio_id}/analysis")
async def analyze_portfolio(
    portfolio_id: int,
    token: Optional[str] = Depends(get_blueant_token),
    ollama_token: Optional[str] = Depends(get_ollama_token)
):
    """Analyze all projects in a portfolio and create an AI summary."""
    if not token:
        raise HTTPException(status_code=401, detail="Missing Blue Ant API key. Please provide it in the headers or query.")
    
    analysis = await analysis_service.analyze_portfolio(portfolio_id, api_key=token, ollama_api_key=ollama_token)
    if "error" in analysis:
        raise HTTPException(status_code=analysis.get("status_code", 404), detail=analysis["error"])
    return analysis

@app.get("/api/project/{project_id}/analysis")
async def analyze_project(
    project_id: int,
    token: Optional[str] = Depends(get_blueant_token),
    ollama_token: Optional[str] = Depends(get_ollama_token)
):
    """Analyze a single project in detail."""
    if not token:
        raise HTTPException(status_code=401, detail="Missing Blue Ant API key. Please provide it in the headers or query.")
    
    analysis = await analysis_service.analyze_project(project_id, api_key=token, ollama_api_key=ollama_token)
    if "error" in analysis:
        raise HTTPException(status_code=analysis.get("status_code", 404), detail=analysis["error"])
    return analysis

@app.get("/api/prompts")
async def get_prompts():
    """Read prompts.yaml and return the templates directly."""
    if not os.path.exists(PROMPTS_PATH):
        raise HTTPException(status_code=404, detail="prompts.yaml not found.")
    
    try:
        with open(PROMPTS_PATH, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f) or {}
        return content
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read prompts.yaml: {str(e)}")

@app.put("/api/prompts")
async def update_prompts(payload: PromptsUpdate):
    """Write updated prompt templates to prompts.yaml."""
    try:
        data = {
            "system_prompt": payload.system_prompt,
            "project_analysis_prompt": payload.project_analysis_prompt,
            "portfolio_analysis_prompt": payload.portfolio_analysis_prompt
        }
        with open(PROMPTS_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False)
        return {"status": "success", "message": "prompts.yaml updated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write prompts.yaml: {str(e)}")

@app.get("/api/config")
async def get_config():
    """Read config.yaml parameters (hiding sensitive keys)."""
    if not os.path.exists(CONFIG_PATH):
        raise HTTPException(status_code=404, detail="config.yaml not found.")
    
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f) or {}
        
        # Strip sensitive credentials before returning
        if "blueant" in content:
            content["blueant"]["api_key_configured"] = bool(settings.blueant_api_key)
        if "ollama" in content:
            content["ollama"]["api_key_configured"] = bool(settings.ollama_api_key)
            
        return content
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read config.yaml: {str(e)}")

@app.put("/api/config")
async def update_config(payload: FullConfigUpdate):
    """Save updated parameters back into config.yaml."""
    try:
        # Load existing file to preserve environment API keys if present
        existing_data = {}
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                existing_data = yaml.safe_load(f) or {}

        # Merge new parameters
        data = {
            "blueant": {
                "url": payload.blueant.url,
                "cache_ttl": payload.blueant.cache_ttl
            },
            "ollama": {
                "url": payload.ollama.url,
                "model": payload.ollama.model,
                "retries": payload.ollama.retries,
                "timeout": payload.ollama.timeout
            }
        }
        
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False)
            
        # Re-initialize configuration loader (env vars still take precedence, matching startup behavior)
        settings.load_from_yaml()
        settings.load_from_env()

        return {"status": "success", "message": "config.yaml updated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config.yaml: {str(e)}")
