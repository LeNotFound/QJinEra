import tomli
import os
from typing import Dict, Any

class Config:
    _instance = None
    _config_data: Dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self):
        config_path = "config.toml"
        if not os.path.exists(config_path):
            # Fallback for development or if running from a different dir
            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.toml")
        
        if os.path.exists(config_path):
            with open(config_path, "rb") as f:
                self._config_data = tomli.load(f)
        else:
            print(f"Warning: {config_path} not found. Using empty config.")

    def get(self, section: str, key: str = None, default: Any = None) -> Any:
        """
        Get a configuration value.
        Usage:
            config.get("bot", "name")
            config.get("llm")
        """
        section_data = self._config_data.get(section, {})
        if key is None:
            return section_data
        return section_data.get(key, default)

    def reload(self):
        self._load_config()

# Global instance
settings = Config()
