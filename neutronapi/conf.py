"""
Settings configuration for NeutronAPI.
"""
import os
import sys
import importlib
from typing import Any, Optional


class ImproperlyConfigured(Exception):
    """Raised when NeutronAPI is somehow improperly configured."""
    pass


class Settings:
    """
    Settings object that loads configuration from a settings module.
    Provides a centralized configuration management system.
    """

    # Required settings that must be defined
    REQUIRED_SETTINGS = ['ENTRY']

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
            # Only provide default settings if we're developing/testing NeutronAPI itself
            if settings_module == 'apps.settings' and self._is_neutronapi_development():
                print("No settings module found. Using default test configuration for NeutronAPI core library.")
                self._use_default_test_settings()
            else:
                raise ImportError(
                    f"Could not import settings module '{settings_module}'. "
                    f"Make sure it exists and is importable. "
                    f"You can also set NEUTRONAPI_SETTINGS_MODULE environment variable. "
                    f"Error: {e}"
                )

        # Validate required settings
        self._validate_required_settings()

    def _is_neutronapi_development(self):
        """Check if we're in the NeutronAPI development/source directory."""
        cwd = os.getcwd()
        
        # Check if we're in the NeutronAPI source repository
        # Look for neutronapi package directory and setup.py/pyproject.toml
        neutronapi_pkg = os.path.join(cwd, 'neutronapi')
        setup_py = os.path.join(cwd, 'setup.py')
        pyproject_toml = os.path.join(cwd, 'pyproject.toml')
        
        is_source_dir = (
            os.path.isdir(neutronapi_pkg) and 
            (os.path.isfile(setup_py) or os.path.isfile(pyproject_toml))
        )
        
        # Also check if we can find neutronapi's own tests directory
        neutronapi_tests = os.path.join(cwd, 'neutronapi', 'tests')
        has_neutron_tests = os.path.isdir(neutronapi_tests)
        
        return is_source_dir and has_neutron_tests

    def _use_default_test_settings(self):
        """Use default test settings for NeutronAPI core library testing."""
        import os
        
        # Determine database engine from environment
        engine = 'aiosqlite'  # Default to SQLite
        db_config = {
            'ENGINE': 'aiosqlite',
            'NAME': ':memory:',
        }
        
        # Check if PostgreSQL is requested
        if os.getenv('DATABASE_PROVIDER', '').lower() == 'asyncpg':
            engine = 'asyncpg'
            db_config = {
                'ENGINE': 'asyncpg',
                'HOST': '127.0.0.1',
                'PORT': 5432,
                'NAME': 'neutronapi_test',
                'USER': 'postgres',
                'PASSWORD': 'postgres',
            }
        
        self._settings = {
            'ENTRY': 'neutronapi.tests.entry:app',  # Dummy entry for tests
            'DATABASES': {
                'default': db_config
            }
        }
        print(f"Using default test configuration with {engine}")

    def _validate_required_settings(self):
        """Validate that all required settings are present."""
        missing_settings = []

        for setting_name in self.REQUIRED_SETTINGS:
            if setting_name not in self._settings:
                missing_settings.append(setting_name)

        if missing_settings:
            raise ImproperlyConfigured(
                f"Missing required settings: {', '.join(missing_settings)}. "
                f"Please add them to your settings module."
            )

        # Validate DATABASES structure if present
        if 'DATABASES' in self._settings:
            databases = self._settings['DATABASES']
            if not isinstance(databases, dict):
                raise ImproperlyConfigured("DATABASES setting must be a dictionary.")

            if 'default' not in databases:
                raise ImproperlyConfigured("DATABASES must contain a 'default' database configuration.")

            default_db = databases['default']
            if not isinstance(default_db, dict):
                raise ImproperlyConfigured("Database configuration must be a dictionary.")

            required_db_keys = ['ENGINE', 'NAME']
            missing_db_keys = [key for key in required_db_keys if key not in default_db]
            if missing_db_keys:
                raise ImproperlyConfigured(
                    f"Default database configuration missing required keys: {', '.join(missing_db_keys)}"
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
