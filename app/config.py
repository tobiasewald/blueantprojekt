import os
import yaml
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = os.environ.get("CONFIG_PATH", str(BASE_DIR / "config.yaml"))
PROMPTS_PATH = os.environ.get("PROMPTS_PATH", str(BASE_DIR / "prompts.yaml"))

class Config:
    def __init__(self):
        self.blueant_url = "https://dashboard-examples.blueant.cloud/rest"
        self.blueant_api_key = os.environ.get("BLUEANT_API_KEY", "")
        self.blueant_cache_ttl = 600

        self.ollama_url = "http://localhost:11434"
        self.ollama_model = "llama3"
        self.ollama_api_key = os.environ.get("OLLAMA_API_KEY", "")
        self.ollama_retries = 3
        self.ollama_timeout = 60

        # Load from config file if exists
        self.load_from_yaml()

        # Env overrides override yaml
        self.load_from_env()

    def load_from_yaml(self):
        if not os.path.exists(CONFIG_PATH):
            return

        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            # Blue Ant config
            ba_data = data.get("blueant", {})
            self.blueant_url = ba_data.get("url", self.blueant_url)
            self.blueant_cache_ttl = int(ba_data.get("cache_ttl", self.blueant_cache_ttl))

            # Ollama config
            ol_data = data.get("ollama", {})
            self.ollama_url = ol_data.get("url", self.ollama_url)
            self.ollama_model = ol_data.get("model", self.ollama_model)
            self.ollama_retries = int(ol_data.get("retries", self.ollama_retries))
            self.ollama_timeout = int(ol_data.get("timeout", self.ollama_timeout))

        except Exception as e:
            print(f"Warning: Failed to load config.yaml: {e}")

    def load_from_env(self):
        # Override with env variables if present
        self.blueant_url = os.environ.get("BLUEANT_URL", self.blueant_url)
        self.blueant_api_key = os.environ.get("BLUEANT_API_KEY", self.blueant_api_key)
        self.blueant_cache_ttl = int(os.environ.get("BLUEANT_CACHE_TTL", str(self.blueant_cache_ttl)))

        self.ollama_url = os.environ.get("OLLAMA_URL", self.ollama_url)
        self.ollama_model = os.environ.get("OLLAMA_MODEL", self.ollama_model)
        self.ollama_api_key = os.environ.get("OLLAMA_API_KEY", self.ollama_api_key)
        self.ollama_retries = int(os.environ.get("OLLAMA_RETRIES", str(self.ollama_retries)))
        self.ollama_timeout = int(os.environ.get("OLLAMA_TIMEOUT", str(self.ollama_timeout)))

# Global config instance
settings = Config()
