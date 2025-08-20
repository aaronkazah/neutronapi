"""
Django-style settings configuration for NeutronAPI.
"""
import os
import sys
import importlib
from typing import Any, Optional


class Settings:
    """
    Settings object that loads configuration from a settings module.
    Similar to Django's settings pattern.
    """
    
    def __init__(self):
        self._settings_module = None
        self._settings = None
        self._setup()
    
    def _setup(self):
        """Setup settings by loading the specified settings module."""
        settings_module = os.environ.get(
            'NEUTRONAPI_SETTINGS_MODULE', 
            'apps.settings'
        )
        
        try:
            # Add current working directory to Python path
            cwd = os.getcwd()
            if cwd not in sys.path:
                sys.path.insert(0, cwd)
                
            self._settings_module = importlib.import_module(settings_module)
            self._settings = {
                name: getattr(self._settings_module, name)
                for name in dir(self._settings_module)
                if not name.startswith('_')
            }
        except ImportError as e:
            raise ImportError(
                f"Could not import settings module '{settings_module}'. "
                f"Make sure it exists and is importable. "
                f"You can also set NEUTRONAPI_SETTINGS_MODULE environment variable. "
                f"Error: {e}"
            )
    
    def __getattr__(self, name: str) -> Any:
        """Get a setting value."""
        if self._settings is None:
            self._setup()
            
        if name in self._settings:
            return self._settings[name]
            
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
    
    def get(self, name: str, default: Any = None) -> Any:
        """Get a setting value with a default fallback."""
        try:
            return getattr(self, name)
        except AttributeError:
            return default


def get_app_from_entry(entry_point: Optional[str] = None):
    """
    Load the ASGI application from the entry point.
    
    Args:
        entry_point: Entry point in format "module:variable" 
                    (e.g., "apps.entry:app"). If None, uses settings.ENTRY
    """
    if entry_point is None:
        # Use settings to get the entry point
        settings = Settings()
        entry_point = getattr(settings, 'ENTRY', 'apps.entry:app')
    
    if ':' not in entry_point:
        raise ValueError(
            f"Invalid entry point format '{entry_point}'. "
            f"Expected format: 'module:variable' (e.g., 'apps.entry:app')"
        )
    
    module_path, app_name = entry_point.split(':', 1)
    
    try:
        # Add current working directory to Python path
        cwd = os.getcwd()
        if cwd not in sys.path:
            sys.path.insert(0, cwd)
            
        module = importlib.import_module(module_path)
        app = getattr(module, app_name)
        return app
    except ImportError as e:
        raise ImportError(
            f"Could not import module '{module_path}' from entry point '{entry_point}'. "
            f"Make sure the module exists and is importable. Error: {e}"
        )
    except AttributeError as e:
        raise AttributeError(
            f"Module '{module_path}' has no attribute '{app_name}'. "
            f"Make sure '{app_name}' is defined in {module_path}. Error: {e}"
        )


# Global settings instance
settings = Settings()