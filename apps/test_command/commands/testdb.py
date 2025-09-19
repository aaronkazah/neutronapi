import os
import sys
from typing import List


class Command:
    """Test database access in custom command."""

    def __init__(self):
        self.help = "Test database access in custom command"

    async def handle(self, args: List[str]) -> None:
        """Test database operations."""
        try:
            # Just test if database connection is working
            from neutronapi.db import get_databases

            print("🔍 Testing database connection...")

            databases = get_databases()
            connection = await databases.get_connection('default')

            print("✅ Database connection established")

            # Try a simple query
            result = await connection.execute("SELECT 1 as test")
            print(f"✅ Simple query worked: {result}")

            print("🎉 Database connection test completed successfully!")

        except Exception as e:
            print(f"❌ Database test failed: {e}")
            if os.environ.get('DEBUG', 'False').lower() == 'true':
                import traceback
                traceback.print_exc()
            sys.exit(1)