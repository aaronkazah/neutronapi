import unittest
import os
from neutronapi.db.queryset import QuerySet, Q
from neutronapi.db.connection import get_databases


class TestQuerySetSQLite(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Use default test DB provider bootstrapped by manage.py
        conn = await get_databases().get_connection('default')
        self.provider = conn.provider
        # Ensure a clean table for this class's inserts
        try:
            await self.provider.execute("DELETE FROM objects")
        except Exception:
            pass

    async def test_crud_and_filters(self):
        # Use QuerySet.create to abstract inserts
        qs = QuerySet(self.provider, table='objects', json_fields={'meta', 'store', 'connections'})
        await qs.create(
            id="obj-1",
            key="/org-1/files/a.txt",
            name="A",
            kind="file",
            meta={"tag": "alpha"},
            folder="/org-1/files",
            parent="/org-1",
        )
        await qs.create(
            id="obj-2",
            key="/org-1/files/b.txt",
            name="B",
            kind="file",
            meta={"tag": "beta"},
            folder="/org-1/files",
            parent="/org-1",
        )

        qs = QuerySet(self.provider, table='objects', json_fields={'meta', 'store', 'connections'})

        # Count
        count = await qs.count()
        self.assertEqual(count, 2)

        # Filter by folder
        folder = '/org-1/files'
        results = await qs.filter(folder=folder).all()
        self.assertEqual(len(results), 2)

        # values_list flat
        names = await qs.values_list('name', flat=True).all()
        self.assertIn('A', names)
        self.assertIn('B', names)

        # JSON field contains
        alpha = await qs.filter(meta__tag__exact='alpha').first()
        self.assertIsNotNone(alpha)
        self.assertEqual(alpha.name, 'A')

        # Ordering
        ordered = await qs.order_by('-name').values_list('name', flat=True).all()
        self.assertEqual(ordered, ['B', 'A'])

        # Pagination
        page1 = await qs.order_by('name').limit(1).values_list('name', flat=True).all()
        self.assertEqual(page1, ['A'])
        page2 = await qs.order_by('name').limit(1).offset(1).values_list('name', flat=True).all()
        self.assertEqual(page2, ['B'])

        # Complex Q combinations
        res = await qs.filter(Q(name='A') | Q(meta__tag__exact='beta')).values_list('name', flat=True).all()
        self.assertCountEqual(res, ['A', 'B'])
