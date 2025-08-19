import os
import unittest
from neutronapi.db.queryset import QuerySet
from neutronapi.db.connection import get_databases


@unittest.skipUnless(os.getenv('DATABASE_PROVIDER', '').lower() == 'asyncpg', 'PostgreSQL tests disabled (set DATABASE_PROVIDER=asyncpg)')
class TestQuerySetPostgres(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        conn = await get_databases().get_connection('default')
        self.provider = conn.provider
        # Ensure clean slate
        try:
            await self.provider.execute("TRUNCATE objects")
        except Exception:
            try:
                await self.provider.execute("DELETE FROM objects")
            except Exception:
                pass

    async def asyncTearDown(self):
        pass

    async def test_queryset_pg(self):
        # Insert with provider
        await self.provider.execute(
            "INSERT INTO objects (id, key, name, kind, meta, created, modified) VALUES ($1, $2, $3, $4, $5::jsonb, NOW(), NOW())",
            ("obj-1", "/org-1/test/a.txt", "A", "file", self.provider.serialize({"tag": "alpha"})),
        )
        await self.provider.execute(
            "INSERT INTO objects (id, key, name, kind, meta, created, modified) VALUES ($1, $2, $3, $4, $5::jsonb, NOW(), NOW())",
            ("obj-2", "/org-1/test/b.txt", "B", "file", self.provider.serialize({"tag": "beta"})),
        )

        qs = QuerySet(self.provider, table='objects', json_fields={'meta', 'store', 'connections'})
        count = await qs.count()
        self.assertEqual(count, 2)
        alpha = await qs.filter(meta__tag__exact='alpha').first()
        self.assertIsNotNone(alpha)
        self.assertEqual(alpha.name, 'A')
