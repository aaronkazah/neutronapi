"""
File-based migration tracking system with hash validation.
"""
import hashlib
import re
import importlib.util
import inspect
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Set

from neutronapi.db.connection import DatabaseType
from neutronapi.db.migrations import Migration


class MigrationRecord:
    """Represents a migration record in the database."""
    
    def __init__(self, app_label: str, migration_name: str, file_hash: str, applied_at: datetime):
        self.app_label = app_label
        self.migration_name = migration_name
        self.file_hash = file_hash
        self.applied_at = applied_at
    
    def __repr__(self):
        return f"<MigrationRecord {self.app_label}.{self.migration_name}>"


class MigrationFile:
    """Represents a migration file on disk."""
    
    def __init__(self, app_label: str, migration_name: str, file_path: Path):
        self.app_label = app_label
        self.migration_name = migration_name
        self.file_path = file_path
        self._hash = None
        self._module = None
    
    @property
    def file_hash(self) -> str:
        """Calculate SHA-256 hash of migration file content."""
        if self._hash is None:
            with open(self.file_path, 'rb') as f:
                self._hash = hashlib.sha256(f.read()).hexdigest()
        return self._hash
    
    @property
    def module(self):
        """Load the migration module."""
        if self._module is None:
            spec = importlib.util.spec_from_file_location(
                f"{self.app_label}.migrations.{self.migration_name}", 
                self.file_path
            )
            self._module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self._module)
        return self._module
    
    @property
    def migration(self):
        """Get the Migration instance from the module."""
        # First, try the simple module-level variable pattern
        m = getattr(self.module, 'migration', None)
        if m is not None:
            return m

        # Fallback: search for a subclass of Migration defined in this module
        for name, obj in vars(self.module).items():
            if (
                inspect.isclass(obj)
                and issubclass(obj, Migration)
                and obj is not Migration
                and obj.__module__ == self.module.__name__
            ):
                operations = getattr(obj, 'operations', [])
                dependencies = getattr(obj, 'dependencies', [])
                try:
                    return obj(self.app_label, operations=operations, dependencies=dependencies)
                except TypeError:
                    return obj(self.app_label, operations=operations)
        return None
    
    def __repr__(self):
        return f"<MigrationFile {self.app_label}.{self.migration_name}>"


class MigrationTracker:
    """
    Tracks applied migrations using a database table with file hash validation.
    
    This system uses numbered migration files (001_initial.py, 002_add_users.py)
    and stores their hashes to detect changes.
    """
    
    MIGRATION_TABLE = 'neutronapi_migrations'
    
    def __init__(self, base_dir: str = "apps"):
        self.base_dir = Path(base_dir)
    
    async def ensure_migration_table(self, connection) -> None:
        """Create the migration tracking table if it doesn't exist."""
        # Use the provider from the given connection
        provider = connection.provider
        
        # Create migrations table based on connection type
        if connection.db_type == DatabaseType.SQLITE:
            sql = f"""
            CREATE TABLE IF NOT EXISTS {self.MIGRATION_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_label TEXT NOT NULL,
                migration_name TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(app_label, migration_name)
            )
            """
        elif connection.db_type == DatabaseType.POSTGRES:
            sql = f"""
            CREATE TABLE IF NOT EXISTS {self.MIGRATION_TABLE} (
                id SERIAL PRIMARY KEY,
                app_label VARCHAR(255) NOT NULL,
                migration_name VARCHAR(255) NOT NULL,
                file_hash VARCHAR(64) NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(app_label, migration_name)
            )
            """
        else:
            raise ValueError(f"Unsupported database type: {connection.db_type}")
        
        await connection.execute(sql)
    
    def discover_migration_files(self) -> Dict[str, List[MigrationFile]]:
        """
        Discover migration files in apps/*/migrations/ directories.
        
        Expected structure:
        apps/
        ├── core/
        │   └── migrations/
        │       ├── 001_initial.py
        │       ├── 002_add_users.py
        │       └── __init__.py
        └── blog/
            └── migrations/
                ├── 001_initial.py
                └── __init__.py
        
        Returns:
            Dict mapping app_label to sorted list of MigrationFile objects
        """
        app_migrations = {}
        migration_pattern = re.compile(r'^(\d{3,4})_(.+)\.py$')
        
        if not self.base_dir.exists():
            return app_migrations
        
        for app_dir in self.base_dir.iterdir():
            if not app_dir.is_dir() or app_dir.name.startswith('.'):
                continue
            
            migrations_dir = app_dir / 'migrations'
            if not migrations_dir.exists():
                continue
            
            app_label = app_dir.name
            migrations = []
            
            for migration_file in migrations_dir.iterdir():
                if not migration_file.is_file() or migration_file.name.startswith('__'):
                    continue
                
                match = migration_pattern.match(migration_file.name)
                if match:
                    number, name = match.groups()
                    migration_name = f"{number}_{name}"
                    migrations.append(MigrationFile(app_label, migration_name, migration_file))
            
            # Sort by migration number
            migrations.sort(key=lambda m: int(m.migration_name.split('_')[0]))
            app_migrations[app_label] = migrations
        
        return app_migrations
    
    async def get_applied_migrations(self, connection) -> Dict[str, Set[str]]:
        """Get all applied migrations from the database."""
        await self.ensure_migration_table(connection)
        
        rows = await connection.fetch_all(
            f"SELECT app_label, migration_name FROM {self.MIGRATION_TABLE}"
        )
        
        applied = {}
        for row in rows:
            app_label, migration_name = row['app_label'], row['migration_name']
            if app_label not in applied:
                applied[app_label] = set()
            applied[app_label].add(migration_name)
        
        return applied
    
    async def get_migration_record(self, connection, app_label: str, migration_name: str) -> Optional[MigrationRecord]:
        """Get a specific migration record from the database."""
        # Use proper placeholder syntax based on database type
        if hasattr(connection, 'db_type') and connection.db_type == DatabaseType.POSTGRES:
            query = f"SELECT app_label, migration_name, file_hash, applied_at FROM {self.MIGRATION_TABLE} WHERE app_label = $1 AND migration_name = $2"
        else:
            query = f"SELECT app_label, migration_name, file_hash, applied_at FROM {self.MIGRATION_TABLE} WHERE app_label = ? AND migration_name = ?"
        
        row = await connection.fetch_one(query, (app_label, migration_name))
        
        if row:
            return MigrationRecord(row['app_label'], row['migration_name'], row['file_hash'], row['applied_at'])
        return None
    
    async def mark_migration_applied(self, connection, migration_file: MigrationFile) -> None:
        """Mark a migration as applied in the database."""
        # Use proper upsert syntax based on database type
        if hasattr(connection, 'db_type') and connection.db_type == DatabaseType.POSTGRES:
            query = f"""
                INSERT INTO {self.MIGRATION_TABLE} (app_label, migration_name, file_hash) 
                VALUES ($1, $2, $3)
                ON CONFLICT (app_label, migration_name) 
                DO UPDATE SET file_hash = $3
            """
        else:
            query = f"""
                INSERT OR REPLACE INTO {self.MIGRATION_TABLE} 
                (app_label, migration_name, file_hash) VALUES (?, ?, ?)
            """
        
        await connection.execute(query, (migration_file.app_label, migration_file.migration_name, migration_file.file_hash))
        if hasattr(connection, 'commit'):
            await connection.commit()
    
    async def get_unapplied_migrations(self, connection) -> List[MigrationFile]:
        """
        Get all unapplied migrations, including those whose file hash has changed.
        
        Returns migrations in dependency order.
        """
        all_migrations = self.discover_migration_files()
        applied_migrations = await self.get_applied_migrations(connection)
        
        unapplied = []
        
        for app_label, migrations in all_migrations.items():
            applied_for_app = applied_migrations.get(app_label, set())
            
            for migration_file in migrations:
                # Check if migration was never applied
                if migration_file.migration_name not in applied_for_app:
                    unapplied.append(migration_file)
                    continue
                
                # Check if file hash changed (migration was modified)
                record = await self.get_migration_record(
                    connection, app_label, migration_file.migration_name
                )
                if record and record.file_hash != migration_file.file_hash:
                    print(f"WARNING: Migration {app_label}.{migration_file.migration_name} "
                          f"file content changed! Re-applying...")
                    unapplied.append(migration_file)
        
        # Sort by app_label, then by migration number
        unapplied.sort(key=lambda m: (m.app_label, int(m.migration_name.split('_')[0])))
        return unapplied
    
    async def apply_migration(self, connection, migration_file: MigrationFile) -> None:
        """Apply a single migration file."""
        print(f"Applying {migration_file.app_label}.{migration_file.migration_name}...")
        
        try:
            # Load and execute the migration
            migration = migration_file.migration
            if migration:
                # Get database provider from the active connection
                provider = connection.provider
                await migration.apply(None, provider, connection)
                
                # Only mark as applied if migration succeeded without exception
                await self.mark_migration_applied(connection, migration_file)
                print(f"✓ Applied {migration_file.app_label}.{migration_file.migration_name}")
            else:
                raise ValueError(f"No migration found in {migration_file.migration_name}")
            
        except Exception as e:
            print(f"✗ Failed to apply {migration_file.app_label}.{migration_file.migration_name}: {e}")
            # Don't mark as applied if it failed
            raise
    
    async def migrate(self, connection) -> None:
        """Run all unapplied migrations."""
        unapplied = await self.get_unapplied_migrations(connection)
        
        if not unapplied:
            print("No migrations to apply.")
            return
        
        print(f"Applying {len(unapplied)} migrations:")
        for migration_file in unapplied:
            await self.apply_migration(connection, migration_file)
        
        print("All migrations applied successfully!")
    
    def show_migrations(self) -> None:
        """Show all discovered migration files."""
        all_migrations = self.discover_migration_files()
        
        if not all_migrations:
            print("No migration files found.")
            return
        
        for app_label, migrations in all_migrations.items():
            print(f"\n{app_label}:")
            for migration_file in migrations:
                print(f"  {migration_file.migration_name}")
