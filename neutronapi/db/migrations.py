# core/db/migrations.py
import importlib
import inspect
import sys
import textwrap
import traceback
import os
import importlib.util
import json
import datetime
from abc import ABC, abstractmethod

from pathlib import Path
from typing import List, Type, Dict, Set, Optional
from enum import Enum

from neutronapi.db.fields import EnumField, BaseField
from neutronapi.db.connection import get_databases, DatabaseType
from neutronapi.db.models import Model  # Import Model


class Migration:
    def __init__(self, app_label, operations, dependencies=None):
        self.app_label = app_label
        self.dependencies = dependencies or []
        self.operations = operations

    async def apply(self, project_state, provider, connection):
        """Apply migration operations"""
        for operation in self.operations:
            await operation.database_forwards(
                app_label=self.app_label,
                provider=provider,
                from_state=None,
                to_state=project_state,
                connection=connection,
            )

    def __repr__(self):
        return f"<Migration {self.app_label}>"


class Operation(ABC):
    def _get_table_name(self, app_label, model_name_with_prefix):
        """
        Gets the full conventional table name ('app_label_modelname')
        from a potentially prefixed model name ('app_label.ModelName').
        """
        if "." in model_name_with_prefix:
            prefix, name_part = model_name_with_prefix.split(".", 1)
            # Convert to snake_case properly
            snake_case_name = "".join(
                ["_" + c.lower() if c.isupper() else c.lower() for c in name_part]
            ).lstrip("_")
            # Return the FULL conventional name using the prefix from the model name
            return f"{prefix}_{snake_case_name}"
        else:
            # If no prefix, assume it's just ModelName and prepend app_label
            snake_case_name = "".join(
                [
                    "_" + c.lower() if c.isupper() else c.lower()
                    for c in model_name_with_prefix
                ]
            ).lstrip("_")
            return f"{app_label}_{snake_case_name}"

    def _extract_base_table_name(self, app_label: str, full_table_name: str) -> str:
        """Helper to get the model part ('modelname') of the table name ('app_label_modelname')."""
        prefix = f"{app_label}_"
        if full_table_name.startswith(prefix):
            return full_table_name[len(prefix) :]
        else:
            # Log or raise error? This indicates a naming inconsistency.
            print(
                f"WARNING: Could not extract base table name from '{full_table_name}' using app label '{app_label}'. Returning full name."
            )
            return full_table_name  # Fallback

    @abstractmethod
    async def database_forwards(
        self, app_label, provider, from_state, to_state, connection
    ):
        """Performs the database operation forwards."""

    @abstractmethod
    async def database_backwards(
        self, app_label, provider, from_state, to_state, connection
    ):
        """Performs the database operation in reverse."""

    @abstractmethod
    def describe(self):
        """Returns a human-readable description of the operation."""


class CreateModel(Operation):
    def __init__(self, model_name, fields: Dict[str, BaseField], search_meta: Optional[dict] = None):
        self.model_name = model_name  # Expected format: 'app_label.ModelName'
        self.fields = fields
        self.search_meta = search_meta or None

    async def database_forwards(
        self, app_label, provider, from_state, to_state, connection
    ):
        field_items = list(self.fields.items())  # Ensure it's a list of tuples
        # Get the full conventional table name (e.g., 'app_label_model_name')
        full_table_name = self._get_table_name(app_label, self.model_name)
        # Extract the base part ('model_name') required by the schema editor
        table_base_name = self._extract_base_table_name(app_label, full_table_name)

        # Call create_table with separate app_label (schema) and base name (table)
        await provider.create_table(app_label, table_base_name, field_items)
        # After creating the base table, setup full-text search structures.
        # If no explicit search_meta was provided, infer sensible defaults so users need no extra steps.
        try:
            if hasattr(provider, 'setup_full_text'):
                meta = self.search_meta
                if not meta:
                    # Infer default meta: include all text-like fields.
                    inferred = []
                    try:
                        from .fields import CharField, TextField
                        for name, fld in (self.fields or {}).items():
                            if isinstance(fld, (CharField, TextField)):
                                inferred.append(name)
                    except Exception:
                        for name, fld in (self.fields or {}).items():
                            cls_name = getattr(getattr(fld, '__class__', None), '__name__', '')
                            if 'CharField' in cls_name or 'TextField' in cls_name:
                                inferred.append(name)

                    meta = {'search_fields': inferred}
                    # Enable SQLite FTS by default to avoid manual SQL
                    if 'sqlite' in provider.__class__.__name__.lower():
                        meta['sqlite_fts'] = True

                await provider.setup_full_text(app_label, table_base_name, meta, self.fields)
        except Exception as e:
            # Non-fatal: log and continue migrations
            print(f"Warning: FTS setup skipped for {app_label}.{table_base_name}: {e}")

    async def database_backwards(
        self, app_label, provider, from_state, to_state, connection
    ):
        full_table_name = self._get_table_name(app_label, self.model_name)
        table_base_name = self._extract_base_table_name(app_label, full_table_name)
        await provider.drop_table(app_label, table_base_name)

    def describe(self):
        # Format fields for display (assuming field.describe() works)
        field_desc = (
            "{\n"
            + ",\n".join(
                f"            '{name}': {field.describe()}"
                for name, field in self.fields.items()
            )
            + "\n        }"
        )
        # Include search_meta when present
        meta_repr = json.dumps(self.search_meta) if self.search_meta else 'None'
        return f"CreateModel(model_name='{self.model_name}', fields={field_desc}, search_meta={meta_repr})"


class DeleteModel(Operation):
    def __init__(self, model_name):
        self.model_name = model_name  # Expected format: 'app_label.ModelName'

    async def database_forwards(
        self, app_label, provider, from_state, to_state, connection
    ):
        full_table_name = self._get_table_name(app_label, self.model_name)
        table_base_name = self._extract_base_table_name(app_label, full_table_name)
        await provider.drop_table(
            app_label, table_base_name
        )  # Pass schema and base table

    async def database_backwards(
        self, app_label, provider, from_state, to_state, connection
    ):
        # Re-creating the model might be complex, often skipped in backwards
        print(
            f"  Skipping re-creation of model '{self.model_name}' in backwards migration."
        )

    def describe(self):
        return f"DeleteModel(model_name='{self.model_name}')"  # Use original name


class AddField(Operation):
    def __init__(self, model_name, field_name, field: BaseField):  # Type hint
        self.model_name = model_name  # Expected format: 'app_label.ModelName'
        self.field_name = field_name
        self.field = field

    async def database_forwards(
        self, app_label, provider, from_state, to_state, connection
    ):
        full_table_name = self._get_table_name(app_label, self.model_name)
        table_base_name = self._extract_base_table_name(app_label, full_table_name)
        # Pass app_label and table_base_name
        await provider.add_column(
            app_label, table_base_name, self.field_name, self.field
        )

    async def database_backwards(
        self, app_label, provider, from_state, to_state, connection
    ):
        full_table_name = self._get_table_name(app_label, self.model_name)
        table_base_name = self._extract_base_table_name(app_label, full_table_name)
        # Check column existence using schema and table name before removing
        if await provider.column_exists(
            app_label, table_base_name, self.field_name
        ):
            await provider.remove_column(
                app_label, table_base_name, self.field_name
            )
        else:
            print(
                f"  Column '{self.field_name}' not found in '{app_label}.{table_base_name}', skipping removal in backwards migration."
            )

    def describe(self):
        return f"AddField(model_name='{self.model_name}', field_name='{self.field_name}', field={self.field.describe()})"


class RemoveField(Operation):
    def __init__(self, model_name, field_name):
        self.model_name = model_name  # Expected format: 'app_label.ModelName'
        self.field_name = field_name

    async def database_forwards(
        self, app_label, provider, from_state, to_state, connection
    ):
        full_table_name = self._get_table_name(app_label, self.model_name)
        table_base_name = self._extract_base_table_name(app_label, full_table_name)
        await provider.remove_column(app_label, table_base_name, self.field_name)

    async def database_backwards(
        self, app_label, provider, from_state, to_state, connection
    ):
        # Re-adding requires knowing the field definition, often skipped
        print(
            f"  Skipping re-adding field '{self.field_name}' to model '{self.model_name}' in backwards migration (field details unknown)."
        )

    def describe(self):
        return f"RemoveField(model_name='{self.model_name}', field_name='{self.field_name}')"


class AlterField(Operation):
    def __init__(self, model_name, field_name, field):
        self.model_name = model_name  # Expected format: 'app_label.ModelName'
        self.field_name = field_name
        self.field = field

    async def database_forwards(
        self, app_label, provider, from_state, to_state, connection
    ):
        full_table_name = self._get_table_name(app_label, self.model_name)
        table_base_name = self._extract_base_table_name(app_label, full_table_name)
        await provider.alter_column(
            app_label, table_base_name, self.field_name, self.field
        )

    async def database_backwards(
        self, app_label, provider, from_state, to_state, connection
    ):
        # Reverting alterations is complex, often skipped
        print(
            f"  Skipping reversion of field '{self.field_name}' on model '{self.model_name}' in backwards migration (old field details unknown)."
        )

    def describe(self):
        return f"AlterField(model_name='{self.model_name}', field_name='{self.field_name}', field={self.field.describe()})"


class RenameField(Operation):
    def __init__(self, model_name, old_field_name, new_field_name):
        self.model_name = model_name  # Expected format: 'app_label.ModelName'
        self.old_field_name = old_field_name
        self.new_field_name = new_field_name

    async def database_forwards(
        self, app_label, provider, from_state, to_state, connection
    ):
        full_table_name = self._get_table_name(app_label, self.model_name)
        table_base_name = self._extract_base_table_name(app_label, full_table_name)
        await provider.rename_column(
            app_label, table_base_name, self.old_field_name, self.new_field_name
        )

    async def database_backwards(
        self, app_label, provider, from_state, to_state, connection
    ):
        full_table_name = self._get_table_name(app_label, self.model_name)
        table_base_name = self._extract_base_table_name(app_label, full_table_name)
        # Rename back
        await provider.rename_column(
            app_label, table_base_name, self.new_field_name, self.old_field_name
        )

    def describe(self):
        return f"RenameField(model_name='{self.model_name}', old_field_name='{self.old_field_name}', new_field_name='{self.new_field_name}')"


class RenameModel(Operation):
    def __init__(self, old_model_name, new_model_name):
        self.old_model_name = (
            old_model_name  # Expected format: 'app_label.OldModelName'
        )
        self.new_model_name = (
            new_model_name  # Expected format: 'app_label.NewModelName'
        )

    async def database_forwards(
        self, app_label, provider, from_state, to_state, connection
    ):
        """Handle RenameModel operation properly with snake_case conversion."""
        # Extract app label and base names
        old_app, old_base_model = self.old_model_name.split(".", 1)
        new_app, new_base_model = self.new_model_name.split(".", 1)

        # Properly convert CamelCase to snake_case
        def to_snake_case(name):
            return "".join(
                ["_" + c.lower() if c.isupper() else c.lower() for c in name]
            ).lstrip("_")

        # Get the base parts of table names (without app prefix)
        old_snake_case = to_snake_case(old_base_model)
        new_snake_case = to_snake_case(new_base_model)

        # Pass app labels and snake_case base names to rename_table
        await provider.rename_table(
            old_app, old_snake_case, new_app, new_snake_case
        )

    async def database_backwards(
        self, app_label, provider, from_state, to_state, connection
    ):
        # Extract app label and base names
        old_app, old_base_model = self.old_model_name.split(".", 1)
        new_app, new_base_model = self.new_model_name.split(".", 1)

        # Get full table names and extract base parts for schema editor
        old_full_table = self._get_table_name(old_app, old_base_model)
        new_full_table = self._get_table_name(new_app, new_base_model)
        old_base_table = self._extract_base_table_name(old_app, old_full_table)
        new_base_table = self._extract_base_table_name(new_app, new_full_table)

        # Rename back: pass new schema, new base table, old schema, old base table
        await provider.rename_table(
            new_app, new_base_table, old_app, old_base_table
        )

    def describe(self):
        return f"RenameModel(old_model_name='{self.old_model_name}', new_model_name='{self.new_model_name}')"


class MigrationManager:
    def __init__(self, apps=None, base_dir="apps"):
        """
        Initialize MigrationManager with base apps directory

        Args:
            apps (list): Optional list of specific apps to manage
            base_dir (str): Base directory containing all apps (defaults to 'apps')
        """
        self.apps = apps if apps is not None else self._discover_apps(base_dir)
        self.base_dir = base_dir
        self.project_state = {}
        self._models_cache: Dict[str, List[Type[Model]]] = {}  # Use Model type hint

    def _discover_apps(self, base_dir: str) -> List[str]:
        """
        Discover all apps in the base directory

        Args:
            base_dir: Base directory containing all apps

        Returns:
            List of app names that contain a models directory OR models.py file
        """
        apps = []
        for item in os.listdir(base_dir):
            if os.path.isdir(os.path.join(base_dir, item)):
                models_dir = os.path.join(base_dir, item, "models")
                models_file = os.path.join(base_dir, item, "models.py")
                if os.path.isdir(models_dir) or os.path.isfile(models_file):
                    apps.append(item)
        return apps

    def _discover_models(self, app_label: str) -> List[Type]:
        """
        Discover all models in an app's models directory or models.py file
        """
        if app_label in self._models_cache:
            return self._models_cache[app_label]

        models = []
        models_dir = os.path.join(self.base_dir, app_label, "models")
        models_file = os.path.join(self.base_dir, app_label, "models.py")

        # Check for models.py file first
        if os.path.exists(models_file):
            return self._load_models_from_file(app_label, models_file)
        
        # Fall back to models/ directory
        if not os.path.exists(models_dir):
            return models

        import sys
        import importlib

        sys.path.insert(0, self.base_dir)
        importlib.invalidate_caches()

        try:
            for filename in os.listdir(models_dir):
                if filename.endswith(".py") and not filename.startswith("__"):
                    module_name = f"{app_label}.models.{filename[:-3]}"
                    try:
                        module = importlib.import_module(module_name)
                    except Exception:
                        # Fallback: import module directly from file path
                        file_path = os.path.join(models_dir, filename)
                        try:
                            spec = importlib.util.spec_from_file_location(module_name, file_path)
                            if spec and spec.loader:
                                module = importlib.util.module_from_spec(spec)
                                spec.loader.exec_module(module)
                            else:
                                raise ImportError(f"Could not load spec for {module_name}")
                        except Exception:
                            # If even the fallback fails, skip this file
                            continue

                    for name, obj in inspect.getmembers(module):
                        if (
                            inspect.isclass(obj)
                            and hasattr(obj, "_fields")
                            and not name.startswith("_")
                            and obj.__module__.startswith(f"{app_label}.")
                        ):
                            if obj.__name__ != "Model":
                                models.append(obj)
        finally:
            sys.path.remove(self.base_dir)

        self._models_cache[app_label] = models
        return models
    
    def _load_models_from_file(self, app_label: str, models_file: str) -> List[Type]:
        """Load models from a models.py file."""
        models = []
        
        import sys
        import importlib
        import importlib.util
        import inspect
        from neutronapi.db.models import Model

        sys.path.insert(0, self.base_dir)
        importlib.invalidate_caches()

        try:
            module_name = f"{app_label}.models"
            try:
                module = importlib.import_module(module_name)
            except Exception:
                # Fallback: import module directly from file path
                try:
                    spec = importlib.util.spec_from_file_location(module_name, models_file)
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                    else:
                        raise ImportError(f"Could not load spec for {module_name}")
                except Exception:
                    return models

            for name, obj in inspect.getmembers(module):
                if (
                    inspect.isclass(obj)
                    and issubclass(obj, Model)
                    and obj is not Model
                    and obj.__module__ == module.__name__
                ):
                    models.append(obj)

        except Exception as e:
            print(f"Warning: Could not load models from {models_file}: {e}")
        finally:
            if self.base_dir in sys.path:
                sys.path.remove(self.base_dir)

        self._models_cache[app_label] = models
        return models

    async def bootstrap_all(self, test_mode: bool = True):
        """
        Bootstrap all apps. If db is None, each app uses its own database.
        Returns the number of apps that had models and were processed.
        """
        processed_count = 0
        for app_label in self.apps:
            models = self._discover_models(app_label)
            if models:
                # Determine the target DB alias using the router
                target_db_alias = get_databases().router.db_for_app(app_label)
                await self.bootstrap(
                    app_label=app_label,
                    models=models,
                    db=target_db_alias,  # Pass the determined alias
                    test_mode=test_mode,
                )
                processed_count += 1
            else:
                print(f"No models found for app '{app_label}', skipping bootstrap.")
        return processed_count

    async def bootstrap(
        self,
        app_label: str,
        models: Optional[list] = None,
        db: Optional[str] = None,  # This is the target DB ALIAS
        test_mode: bool = True,
        **kwargs,
    ):
        """
        Bootstrap the database with models using provided config.
        If models is None, autodiscover models for the app.
        If db (alias) is None, determine it using the router.
        """
        if models is None:
            models = self._discover_models(app_label)

        if not models:
            print(f"No models found for app {app_label}, skipping bootstrap.")
            return None, None  # Return None if no models

        # Determine target DB alias if not provided
        db_alias = db or get_databases().router.db_for_app(app_label)

        # Get or create connection
        connection = await get_databases().get_connection(db_alias)

        # Determine if we're using PostgreSQL
        is_postgres = getattr(connection, "db_type", None) == DatabaseType.POSTGRES

        # For PostgreSQL, ensure the schema (named after the app_label) exists
        if is_postgres:
            try:
                # Create schema if it doesn't exist
                schema_query = f'CREATE SCHEMA IF NOT EXISTS "{app_label}"'
                await connection.execute(schema_query)
            except Exception as schema_err:
                # This might fail if user lacks permissions, but table creation might still work if schema exists
                print(
                    f"Warning: Could not ensure schema '{app_label}' exists: {schema_err}"
                )

        try:
            # Generate operations (always generate for consistency, even if not writing file)
            operations = await self.makemigrations(
                app_label=app_label,
                models=models,
                return_ops=True,
                clean=test_mode,
            )

            await self.migrate(
                app_label=app_label,
                connection=connection,
                operations=operations if test_mode else None,
            )

            return db_alias, connection

        except Exception as e:
            await connection.rollback()
            raise e

    def _find_enum_location(self, enum_class: Type) -> str:
        """Find the actual module location of an enum by using its __module__ attribute"""
        return enum_class.__module__

    def _get_required_enum_imports(self, operations: List[Operation]) -> List[str]:
        """Determine which enum imports are needed based on the operations"""
        required_enums = set()

        for op in operations:
            if isinstance(op, CreateModel):
                for field in op.fields.values():
                    if isinstance(field, EnumField):
                        enum_class = field.enum_class
                        required_enums.add(
                            f"from {enum_class.__module__} import {enum_class.__name__}"
                        )
            elif isinstance(op, AddField):
                if isinstance(op.field, EnumField):
                    enum_class = op.field.enum_class
                    required_enums.add(
                        f"from {enum_class.__module__} import {enum_class.__name__}"
                    )
            elif isinstance(op, AlterField):
                if isinstance(op.field, EnumField):
                    enum_class = op.field.enum_class
                    required_enums.add(
                        f"from {enum_class.__module__} import {enum_class.__name__}"
                    )

        return sorted(list(required_enums))

    def _generate_migration_file_content(
        self,
        app_label: str,
        operations: List[Operation],
        models: List[Type[Model]],  # Use Model type hint
    ) -> str:
        """Generate the content of a migration file"""
        operations_str = self._format_operations(operations)
        migration_id = int(datetime.datetime.now(datetime.UTC).timestamp())

        # Get required enum imports based on the operations
        enum_imports = self._get_required_enum_imports(operations)

        # Generate state hash from models used to generate this migration
        state = {}
        for model_class in models:
            state[model_class.__name__] = {
                "fields": dict(
                    (name, field.describe())  # Use field.describe() for representation
                    for name, field in model_class._fields.items()
                )
            }
        # Pretty print JSON state hash
        state_json = json.dumps(state, indent=4, sort_keys=True)

        # Generate the file content with HASH at the bottom
        # Ensure all necessary imports are present
        return textwrap.dedent(
            f"""\
# Generated by MigrationManager on {datetime.datetime.now(datetime.UTC).isoformat()}

import datetime
import json
# Ensure all required operation and field types are imported
from neutronapi.db.migrations import Migration, CreateModel, DeleteModel, AddField, RemoveField, AlterField, RenameField, RenameModel
from neutronapi.db.fields import (
    BaseField, CharField, TextField, IntegerField, FloatField, BooleanField,
    DateTimeField, JSONField, VectorField, BinaryField, EnumField
)
from neutronapi.db.models import Model # Import Model base class if needed
# Add specific Enum imports required by this migration
{os.linesep.join(enum_imports) if enum_imports else '# No external Enums needed'}


class Migration{migration_id}(Migration):
    \"\"\"
    Auto-generated migration for {app_label}
    \"\"\"

    # List of dependencies, if any (e.g., [('other_app', '0001_initial')])
    dependencies = []

    operations = [
{operations_str}
    ]

# --- DO NOT EDIT BELOW THIS LINE ---
# This hash represents the state of the models this migration was generated from.
# It is used to detect changes for future migrations.
HASH = {state_json}
"""
        )

    def _get_model_dependencies(self, model: Type) -> Dict[str, Set[Type]]:
        """Recursively get all model and enum dependencies from fields"""
        model_deps = set()
        enum_deps = set()

        # If it's an Enum class, add to enum deps
        if isinstance(model, type) and issubclass(model, Enum):
            enum_deps.add(model)
            return {"models": model_deps, "enums": enum_deps}

        # Process Model fields
        if hasattr(model, "_fields"):
            for field in model._fields.values():
                # Check if field is a reference to another model (adjust based on actual FK implementation)
                # This example assumes a 'related_model' attribute on FK fields
                related_model = getattr(field, "related_model", None)
                if (
                    related_model
                    and inspect.isclass(related_model)
                    and issubclass(related_model, Model)
                    and related_model != model
                ):
                    model_deps.add(related_model)
                    # Recursively get dependencies
                    nested_deps = self._get_model_dependencies(related_model)
                    model_deps.update(nested_deps["models"])
                    enum_deps.update(nested_deps["enums"])

                # Check if field is an enum
                if isinstance(field, EnumField):
                    enum_class = getattr(field, "enum_class", None)
                    if enum_class and issubclass(enum_class, Enum):
                        enum_deps.add(enum_class)

        return {"models": model_deps, "enums": enum_deps}

    def get_migrations_dir(self, app_label: str) -> str:
        """Get the migrations directory path for an app"""
        return os.path.join(self.base_dir, app_label, "migrations")

    def _prefix_model_name(self, app_label: str, model_name: str) -> str:
        """Prefix model name with app label (e.g., 'app_label.ModelName') unless already prefixed."""
        if "." in model_name:
            # Already prefixed (or has dots for other reasons, assume prefixed)
            return model_name
        return f"{app_label}.{model_name}"

    def _detect_changes(
        self,
        previous_state: Dict,
        current_state: Dict,
        models: List[Type[Model]],
        app_label: str,
    ) -> List[Operation]:
        """Detects changes between the previous and current model states."""
        operations: List[Operation] = []
        previous_models = set(previous_state.keys())
        current_models = set(current_state.keys())

        # Create model lookup dict from the current list of models
        model_lookup = {model.__name__: model for model in models}

        # --- Model Renaming Detection (Simple Heuristic) ---
        # Try to find pairs of added/deleted models with similar field structures
        added_models = current_models - previous_models
        deleted_models = previous_models - current_models
        potential_renames = {}  # Map old_name -> new_name

        # VERY basic rename detection: if one added, one deleted, assume rename for now
        # A real implementation needs field comparison.
        if len(added_models) == 1 and len(deleted_models) == 1:
            old_name = deleted_models.pop()
            new_name = added_models.pop()
            potential_renames[old_name] = new_name
            # Add RenameModel operation
            operations.append(
                RenameModel(
                    old_model_name=self._prefix_model_name(app_label, old_name),
                    new_model_name=self._prefix_model_name(app_label, new_name),
                )
            )
            # Adjust previous_state for field comparison
            previous_state[new_name] = previous_state.pop(old_name)
            previous_models.remove(old_name)
            previous_models.add(new_name)

        # --- Detect New Models (excluding those identified as renames) ---
        newly_added_models = current_models - previous_models
        for model_name in newly_added_models:
            if model_name in model_lookup:
                model_class = model_lookup[model_name]
                prefixed_name = self._prefix_model_name(app_label, model_name)
                # Extract optional search meta from model class
                search_meta = None
                meta_cls = getattr(model_class, 'Meta', None)
                if meta_cls is not None:
                    meta_dict = {}
                    for key in ('search_fields', 'search_config', 'search_weights', 'sqlite_fts'):
                        if hasattr(meta_cls, key):
                            meta_dict[key] = getattr(meta_cls, key)
                    search_meta = meta_dict or None
                operations.append(
                    CreateModel(model_name=prefixed_name, fields=model_class._fields, search_meta=search_meta)
                )
            else:
                print(
                    f"Warning: Model '{model_name}' found in current state but not in provided models list."
                )

        # --- Detect Deleted Models (excluding those identified as renames) ---
        newly_deleted_models = previous_models - current_models
        for model_name in newly_deleted_models:
            prefixed_name = self._prefix_model_name(app_label, model_name)
            operations.append(DeleteModel(model_name=prefixed_name))

        # --- Detect Field Changes (for models present in both states or renamed) ---
        for model_name in current_models & previous_models:  # Intersection
            if model_name not in model_lookup:
                print(
                    f"Warning: Model '{model_name}' found in state comparison but not in provided models list."
                )
                continue
            if model_name not in previous_state:
                print(
                    f"Warning: Model '{model_name}' missing from previous state during field comparison."
                )
                continue

            model_class = model_lookup[model_name]
            prefixed_name = self._prefix_model_name(app_label, model_name)

            # Ensure previous state is a dictionary
            previous_model_detail = previous_state[model_name]
            if isinstance(previous_model_detail, str):
                try:
                    previous_model_detail = json.loads(previous_model_detail)
                except json.JSONDecodeError:
                    print(
                        f"Error: Invalid JSON in previous state HASH for {model_name}. Cannot compare fields."
                    )
                    continue  # Skip field comparison for this model

            if (
                not isinstance(previous_model_detail, dict)
                or "fields" not in previous_model_detail
            ):
                print(
                    f"Warning: Previous state for '{model_name}' is not a valid dict with 'fields'. Skipping field comparison."
                )
                continue

            current_fields_state = current_state[model_name].get("fields", {})
            previous_fields_state = previous_model_detail.get("fields", {})

            current_field_names = set(current_fields_state.keys())
            previous_field_names = set(previous_fields_state.keys())

            # --- Field Renaming (Basic Heuristic) ---
            added_fields = current_field_names - previous_field_names
            deleted_fields = previous_field_names - current_field_names
            # Simple case: one added, one deleted -> assume rename
            if len(added_fields) == 1 and len(deleted_fields) == 1:
                old_field = deleted_fields.pop()
                new_field = added_fields.pop()
                # TODO: Add smarter field type comparison for rename detection
                operations.append(
                    RenameField(
                        model_name=prefixed_name,
                        old_field_name=old_field,
                        new_field_name=new_field,
                    )
                )
                # Adjust sets for subsequent checks
                current_field_names.remove(new_field)
                previous_field_names.remove(old_field)
                # Add the renamed field to previous_fields_state for AlterField check
                previous_fields_state[new_field] = previous_fields_state.pop(old_field)
                previous_field_names.add(new_field)

            # --- Added Fields ---
            for field_name in current_field_names - previous_field_names:
                if field_name in model_class._fields:
                    operations.append(
                        AddField(
                            model_name=prefixed_name,
                            field_name=field_name,
                            field=model_class._fields[field_name],
                        )
                    )
                else:
                    print(
                        f"Warning: Field '{field_name}' added to model '{model_name}' state, but not found in class definition."
                    )

            # --- Removed Fields ---
            for field_name in previous_field_names - current_field_names:
                operations.append(
                    RemoveField(model_name=prefixed_name, field_name=field_name)
                )

            # --- Altered Fields ---
            for field_name in (
                current_field_names & previous_field_names
            ):  # Intersection
                # Use .describe() for comparison
                current_desc = model_class._fields[field_name].describe()
                previous_desc = previous_fields_state.get(
                    field_name
                )  # Already a string from HASH/describe()

                if current_desc != previous_desc:
                    if field_name in model_class._fields:
                        operations.append(
                            AlterField(
                                model_name=prefixed_name,
                                field_name=field_name,
                                field=model_class._fields[field_name],
                            )
                        )
                    else:
                        print(
                            f"Warning: Field '{field_name}' altered in model '{model_name}' state, but not found in class definition."
                        )

        return operations

    def _generate_migration_filename(self, migrations_dir):
        """Generate a unique migration filename (e.g., 0001_auto.py)"""
        existing_migrations = [
            f
            for f in os.listdir(migrations_dir)
            if f.endswith(".py")
            and f != "__init__.py"
            and f[:4].isdigit()  # Check first 4 chars are digits
        ]
        existing_numbers = [int(f.split("_")[0]) for f in existing_migrations]
        next_number = max(existing_numbers, default=0) + 1
        # Simple name for now, could add descriptive suffix later
        return f"{str(next_number).zfill(4)}_auto.py"

    def _format_operations(self, operations: List[Operation]) -> str:
        """Format migration operations as Python code string"""
        formatted_ops = []
        for op in operations:
            # Use the describe() method of the operation itself
            desc = op.describe()
            # Indent the description for inclusion in the list
            indented_desc = textwrap.indent(
                desc, " " * 8
            ).lstrip()  # 8 spaces indentation
            formatted_ops.append(indented_desc)

        return ",\n".join(formatted_ops)

    def _build_state_from_migrations(self, app_label: str) -> Dict:
        """
        Build current state from existing migrations.
        
        This method checks for gaps in migration files and returns empty state
        if any are detected, forcing regeneration of missing migrations.
        
        If no gaps are detected, it loads the HASH from the latest migration file.
        """
        state = {}
        migrations_dir = self.get_migrations_dir(app_label)

        if not os.path.exists(migrations_dir):
            print(
                f"No migrations directory found for {app_label}. Starting with empty state."
            )
            return state

        migration_files = sorted(
            [
                f
                for f in os.listdir(migrations_dir)
                if f.endswith(".py")
                and f != "__init__.py"
                and f[:4].isdigit()  # Look for numbered files
            ],
            # Sort numerically based on the prefix
            key=lambda x: int(x.split("_")[0]),
        )

        if not migration_files:
            print(
                f"No numbered migration files found in {migrations_dir}. Starting with empty state."
            )
            return state

        # Check for gaps in migration sequence
        migration_numbers = [int(f.split("_")[0]) for f in migration_files]
        expected_sequence = list(range(1, max(migration_numbers) + 1))
        
        if migration_numbers != expected_sequence:
            missing_numbers = [n for n in expected_sequence if n not in migration_numbers]
            
            # Try to load state from latest migration first
            last_migration_file = migration_files[-1]
            module_path = Path(migrations_dir) / last_migration_file
            module_name = f"{app_label}.migrations.{module_path.stem}"
            
            # Check if latest migration contains all current models
            try:
                # Add base_dir to path temporarily
                path_added = False
                if self.base_dir not in sys.path:
                    sys.path.insert(0, self.base_dir)
                    path_added = True
                    
                # Load the latest migration's HASH
                importlib.invalidate_caches()
                if module_name in sys.modules:
                    del sys.modules[module_name]
                    
                spec = importlib.util.spec_from_file_location(module_name, module_path)
                if spec and spec.loader:
                    migration_module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = migration_module
                    spec.loader.exec_module(migration_module)
                    
                    if hasattr(migration_module, "HASH") and isinstance(migration_module.HASH, dict):
                        # If latest migration has complete state, use it (gaps are ok)
                        print(
                            f"Missing migration files detected for {app_label}: "
                            f"{[str(n).zfill(4) + '_*.py' for n in missing_numbers]}. "
                            f"Using state from latest migration {last_migration_file}."
                        )
                        return migration_module.HASH
                        
            except Exception:
                pass  # Fall through to empty state
            finally:
                if path_added and self.base_dir in sys.path:
                    sys.path.remove(self.base_dir)
                    
            # If we can't load latest migration state, return empty to regenerate
            print(
                f"Missing migration files detected for {app_label}: "
                f"{[str(n).zfill(4) + '_*.py' for n in missing_numbers]}. "
                f"Starting with empty state to regenerate missing migrations."
            )
            return {}

        # No gaps detected - load state from latest migration
        last_migration_file = migration_files[-1]
        module_path = Path(migrations_dir) / last_migration_file
        module_name = f"{app_label}.migrations.{module_path.stem}"

        # Add the base directory to sys.path temporarily if needed
        path_added = False
        if self.base_dir not in sys.path:
            sys.path.insert(0, self.base_dir)
            path_added = True

        try:
            # Invalidate caches to ensure we load the latest version
            importlib.invalidate_caches()
            # Ensure the specific module is removed if it was loaded before
            if module_name in sys.modules:
                del sys.modules[module_name]

            # Load the module using spec_from_file_location for reliability
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if spec and spec.loader:
                migration_module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = (
                    migration_module  # Add to sys.modules before execution
                )
                spec.loader.exec_module(migration_module)

                # Get the HASH dictionary directly from the module
                if hasattr(migration_module, "HASH") and isinstance(
                    migration_module.HASH, dict
                ):
                    state = migration_module.HASH
                else:
                    print(
                        f"Warning: No valid HASH dictionary found in {module_name}. Using empty state."
                    )
            else:
                print(f"Error: Could not create module spec for {module_path}")

        except Exception as e:
            print(f"Error loading migration state from {module_name}: {str(e)}")
            # Print the traceback for debugging
            traceback.print_exc()
            # Decide on behavior: return empty state or raise error?
            # Returning empty state might lead to incorrect migrations. Raising is safer.
            raise RuntimeError(
                f"Failed to load state from migration {module_name}. Cannot proceed."
            ) from e

        finally:
            # Clean up sys.path
            if path_added and self.base_dir in sys.path:
                sys.path.remove(self.base_dir)

        return state

    async def _load_migration(
        self, app_label: str, migrations_dir: str, migration_file: str
    ) -> Migration:
        """Load a single Migration instance from a file."""
        migration_path = Path(migrations_dir) / migration_file
        module_name = f"{app_label}.migrations.{migration_path.stem}"

        # Add base_dir to path if necessary
        path_added = False
        if self.base_dir not in sys.path:
            sys.path.insert(0, self.base_dir)
            path_added = True

        try:
            # Invalidate and remove existing module if present
            importlib.invalidate_caches()
            if module_name in sys.modules:
                del sys.modules[module_name]

            # Load using spec
            spec = importlib.util.spec_from_file_location(module_name, migration_path)
            if spec is None or spec.loader is None:
                raise ImportError(
                    f"Could not load migration file spec: {migration_path}"
                )

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module  # Register module before execution
            spec.loader.exec_module(module)

            # Find the specific Migration subclass within the loaded module
            migration_class = None
            for name, obj in vars(module).items():
                # Check if it's a class, a subclass of Migration, defined in *this* module,
                # and not the base Migration class itself. StartsWith("Migration") is a convention.
                if (
                    inspect.isclass(obj)
                    and issubclass(obj, Migration)
                    and obj is not Migration
                    and obj.__module__ == module_name  # Exclude the base class
                    and name.startswith("Migration")  # Make sure it's defined here
                ):
                    migration_class = obj
                    break  # Found the migration class

            if not migration_class:
                raise ValueError(f"No Migration subclass found in {migration_file}")

            # Instantiate the migration class found
            # The __init__ of Migration takes app_label and operations
            # Operations should be defined as a class variable in the migration file
            operations = getattr(migration_class, "operations", [])
            dependencies = getattr(
                migration_class, "dependencies", []
            )  # Get dependencies too
            migration_instance = migration_class(
                app_label, operations=operations, dependencies=dependencies
            )

            return migration_instance

        except Exception as e:
            print(
                f"Error loading migration {module_name} from {migration_file}: {str(e)}"
            )
            traceback.print_exc()
            raise  # Re-raise to stop the migration process

        finally:
            if path_added and self.base_dir in sys.path:
                sys.path.remove(self.base_dir)
            # Optionally remove module from sys.modules again after use
            # if module_name in sys.modules:
            #      del sys.modules[module_name]

    async def get_migrations(self, app_label=None):
        """
        Gets all Migration instances for an app or all apps, sorted numerically.

        Args:
            app_label (str, optional): Specific app to get migrations for

        Returns:
            dict: Dictionary of app labels to list of Migration instances
        """
        migrations_dict: Dict[str, List[Migration]] = {}

        app_labels_to_process = [app_label] if app_label else self.apps

        for current_app_label in app_labels_to_process:
            migrations_dir = self.get_migrations_dir(current_app_label)

            if not os.path.exists(migrations_dir):
                migrations_dict[current_app_label] = []  # No migrations for this app
                continue

            # Find numbered migration files and sort them
            migration_files = sorted(
                (
                    f
                    for f in os.listdir(migrations_dir)
                    if f.endswith(".py") and f != "__init__.py" and f[:4].isdigit()
                ),
                key=lambda x: int(x.split("_")[0]),  # Sort by number prefix
            )

            app_migrations = []
            for migration_file in migration_files:
                try:
                    migration = await self._load_migration(
                        current_app_label, migrations_dir, migration_file
                    )
                    app_migrations.append(migration)
                except Exception as e:
                    # Log error but potentially continue loading others? Or stop?
                    # Depending on desired behavior, you might want to re-raise e here
                    raise  # Stop processing if a migration fails to load

            migrations_dict[current_app_label] = app_migrations

        return migrations_dict

    async def makemigrations(
        self,
        app_label: str,
        models: List[Type[Model]],  # Use Model type hint
        return_ops: bool = False,
        clean: bool = False,
    ) -> Optional[List[Operation]]:
        """
        Generate migration operations (and optionally write file) by comparing
        current model definitions against the state from the last migration.
        """
        # 1. Discover models if not provided (though usually they are passed in)
        if not models:
            models = self._discover_models(app_label)

        # If still no models, nothing to do
        if not models:
            print(f"No models found for app '{app_label}'. No migrations needed.")
            return [] if return_ops else None

        # 2. Build current state from the provided model classes
        current_state = {}
        for model_class in models:
            # Check if it's actually a Model subclass before processing
            if (
                inspect.isclass(model_class)
                and issubclass(model_class, Model)
                and model_class is not Model
            ):
                current_state[model_class.__name__] = {
                    "fields": {
                        name: field.describe()
                        for name, field in model_class._fields.items()
                    }
                }
            else:
                print(
                    f"Warning: Item '{model_class}' in models list for '{app_label}' is not a valid Model subclass."
                )

        # 3. Build previous state from the HASH in the last migration file
        if clean:
            # 'clean' mode ignores previous state, useful for initial/test migrations
            previous_state = {}
        else:
            # Normal mode: load state from the last migration file
            migrations_dir = self.get_migrations_dir(app_label)
            os.makedirs(migrations_dir, exist_ok=True)  # Ensure directory exists
            # Ensure __init__.py exists
            init_path = os.path.join(migrations_dir, "__init__.py")
            if not os.path.exists(init_path):
                with open(init_path, "w") as f:
                    f.write("")

            # This function now loads the HASH dict
            previous_state = self._build_state_from_migrations(app_label)

        # 4. Detect changes between previous and current states
        operations = self._detect_changes(
            previous_state, current_state, models, app_label
        )

        # 5. Handle output: return operations or write to file
        if not operations:
            return [] if return_ops else None

        if return_ops:
            # Just return the list of operations (e.g., for bootstrap)
            return operations
        else:
            # Write the migration file (normal 'makemigrations' behavior)
            if not clean:  # Don't write file in clean mode
                migrations_dir = self.get_migrations_dir(app_label)
                migration_filename = self._generate_migration_filename(migrations_dir)
                migration_content = self._generate_migration_file_content(
                    app_label=app_label,
                    operations=operations,
                    models=models,  # Pass models for HASH
                )

                filepath = os.path.join(migrations_dir, migration_filename)
                with open(filepath, "w") as f:
                    f.write(migration_content)
                print(f"Migration file created: {filepath}")
            # Return the operations so the command can detect that changes were made
            return operations

    async def migrate(self, app_label, connection, operations=None):
        """Applies migrations to the database."""
        # Determine provider from connection/Database/Provider
        if hasattr(connection, 'provider'):
            provider = connection.provider
        else:
            provider = connection

        # Ensure provider is connected when passed directly
        try:
            if hasattr(provider, 'connect'):
                needs_connect = False
                if hasattr(provider, 'conn'):
                    needs_connect = provider.conn is None
                # Some providers use pools; attempt a lightweight op to verify connectivity
                if needs_connect:
                    await provider.connect()
        except Exception:
            # Let downstream operations surface meaningful errors
            pass

        if operations is not None:
            migration = Migration(app_label, operations)
            try:
                # Apply operations using the schema editor
                await migration.apply(
                    project_state=self.project_state,  # Pass current project state if needed
                    provider=provider,
                    connection=connection,
                )
                if hasattr(connection, 'commit'):
                    await connection.commit()
            except Exception as e:
                print(f"ERROR applying direct operations for {app_label}: {e}")
                try:
                    if hasattr(connection, 'rollback'):
                        await connection.rollback()
                except Exception as rb_err:
                    print(f"Rollback failed: {rb_err}")
                traceback.print_exc()
                raise
            return  # Finish after applying direct operations

            # --- Normal migration process using files ---
            migrations_dir = self.get_migrations_dir(app_label)

            if not os.path.exists(migrations_dir):
                print(
                    f"No migrations directory found for {app_label}. Nothing to migrate."
                )
                return

            # Get all migration files, sorted numerically
            try:
                all_migrations = await self.get_migrations(app_label)
                app_migrations = all_migrations.get(app_label, [])
            except Exception as e:
                print(f"Failed to load migrations for {app_label}: {e}")
                raise  # Stop if loading fails

            if not app_migrations:
                print(f"No migration files found for {app_label}. Nothing to migrate.")
                return

            applied_count = 0
            try:
                for migration in app_migrations:
                    # Apply the migration using the schema editor
                    await migration.apply(
                        project_state=self.project_state,  # Pass state if needed by operations
                        provider=provider,
                        connection=connection,
                    )
                    # Update project_state based on migration? (More complex)
                    applied_count += 1

                # Commit transaction after all migrations for the app are applied
                if hasattr(connection, 'commit'):
                    await connection.commit()

            except Exception as e:
                print(f"ERROR during migration application for {app_label}: {e}")
                # Attempt to rollback
                try:
                    await connection.rollback()
                except Exception as rb_err:
                    print(f"Rollback failed: {rb_err}")
                traceback.print_exc()
                raise  # Re-raise the exception to indicate failure
