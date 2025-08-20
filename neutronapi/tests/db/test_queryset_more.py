import unittest
from neutronapi.db.queryset import QuerySet
from neutronapi.db.connection import get_databases


class TestQuerySetMoreSQLite(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        conn = await get_databases().get_connection('default')
        self.provider = conn.provider
        try:
            await self.provider.execute("DELETE FROM objects")
        except Exception:
            pass

        # Seed data with duplicates and JSON numbers using QuerySet.create
        qs = QuerySet(self.provider, table='objects', json_fields={'meta', 'store', 'connections'})
        await qs.create(
            id="obj-3",
            key="/org-1/files/c.txt",
            name="C",
            kind="file",
            meta={"tag": "alpha", "score": 10},
            folder="/org-1/files",
            parent="/org-1",
        )
        await qs.create(
            id="obj-4",
            key="/org-1/files/d.txt",
            name="A",
            kind="file",
            meta={"tag": "alpha", "score": 3},
            folder="/org-1/files",
            parent="/org-1",
        )

    async def asyncTearDown(self):
        pass

    async def test_values_and_exclude(self):
        qs = QuerySet(self.provider, table='objects', json_fields={'meta', 'store', 'connections'})
        names = await qs.values_list('name', flat=True).all()
        self.assertIn('A', names)
        self.assertIn('C', names)

        excl = await qs.exclude(name='A').values_list('name', flat=True).all()
        self.assertNotIn('A', excl)

    async def test_distinct_and_last(self):
        qs = QuerySet(self.provider, table='objects', json_fields={'meta', 'store', 'connections'})
        distinct_names = await qs.values_list('name', flat=True).distinct('name').all()
        # Both A and C should be present without duplicates
        self.assertCountEqual(distinct_names, ['A', 'C'])

        # last() without explicit order should use -created
        last_obj = await qs.last()
        self.assertIsNotNone(last_obj)
        self.assertIn(last_obj.name, ['A', 'C'])

    async def test_json_lookups(self):
        qs = QuerySet(self.provider, table='objects', json_fields={'meta', 'store', 'connections'})
        high = await qs.filter(meta__score__gt=5).values_list('name', flat=True).all()
        self.assertEqual(high, ['C'])

        alpha = await qs.filter(meta__tag__contains='alp').values_list('name', flat=True).all()
        self.assertCountEqual(alpha, ['C', 'A'])
