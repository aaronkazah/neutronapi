import re
import unittest

from neutronapi.db import Model
from neutronapi.db.connection import get_databases, setup_databases
from neutronapi.db.fields import CharField, JSONField


class BulkPgObject(Model):
    id = CharField(primary_key=True)
    key = CharField(null=False)
    name = CharField(null=True)
    kind = CharField(null=True)
    meta = JSONField(null=True, default=dict)

    class Meta:
        table_name = "test_bulk_pg"


class TestBulkPostgres(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_manager = setup_databases()
        conn = await get_databases().get_connection("default")
        self.provider = conn.provider
        schema, table = BulkPgObject._get_parsed_table_name()
        self.table_identifier = self.provider.get_table_identifier(schema, table)
        await self.provider.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        await self.provider.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.table_identifier} (
                id TEXT PRIMARY KEY,
                key TEXT NOT NULL,
                name TEXT,
                kind TEXT,
                meta JSONB
            )
        """)
        await self.provider.execute(f"DELETE FROM {self.table_identifier}")

    async def asyncTearDown(self):
        await self.provider.execute(f"DROP TABLE IF EXISTS {self.table_identifier}")
        await self.db_manager.close_all()

    def _make(self, **kwargs):
        return BulkPgObject(**kwargs)

    # ---- bulk_create ----

    async def test_bulk_create_inserts_all(self):
        objs = [self._make(id=f"obj-{i:03d}", key=f"k{i}", name=f"n{i}") for i in range(100)]
        await BulkPgObject.objects.bulk_create(objs)

        self.assertEqual(await BulkPgObject.objects.count(), 100)

        first = await BulkPgObject.objects.get(id="obj-000")
        self.assertEqual(first.name, "n0")
        last = await BulkPgObject.objects.get(id="obj-099")
        self.assertEqual(last.name, "n99")

    async def test_bulk_create_auto_pk(self):
        objs = [self._make(key=f"k{i}") for i in range(10)]
        await BulkPgObject.objects.bulk_create(objs)

        ids = [o.id for o in objs]
        self.assertEqual(len(set(ids)), 10)

        ulid_re = re.compile(r"^[0-9A-Za-z]{26}$")
        uuid7_re = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        )
        for pk in ids:
            self.assertTrue(
                isinstance(pk, str) and (ulid_re.match(pk) or uuid7_re.match(pk)),
                f"unexpected id format: {pk!r}",
            )
        self.assertEqual(await BulkPgObject.objects.count(), 10)

    async def test_bulk_create_batches(self):
        objs = [self._make(id=f"x-{i:05d}", key=f"k{i}") for i in range(1200)]
        await BulkPgObject.objects.bulk_create(objs, batch_size=500)
        self.assertEqual(await BulkPgObject.objects.count(), 1200)

    async def test_bulk_create_json_field(self):
        payload = {"tag": "x", "nested": {"a": 1, "b": [1, 2, 3]}}
        objs = [self._make(id=f"j-{i}", key=f"k{i}", meta=payload) for i in range(5)]
        await BulkPgObject.objects.bulk_create(objs)

        reloaded = await BulkPgObject.objects.get(id="j-2")
        self.assertEqual(reloaded.meta, payload)

    async def test_bulk_create_default_upsert(self):
        await BulkPgObject.objects.bulk_create([self._make(id="dup", key="k", name="first")])
        await BulkPgObject.objects.bulk_create([self._make(id="dup", key="k", name="second")])

        row = await BulkPgObject.objects.get(id="dup")
        self.assertEqual(row.name, "second")
        self.assertEqual(await BulkPgObject.objects.count(), 1)

    async def test_bulk_create_ignore_conflicts(self):
        await BulkPgObject.objects.bulk_create([self._make(id="keep", key="k", name="first")])
        await BulkPgObject.objects.bulk_create(
            [self._make(id="keep", key="k", name="second")],
            ignore_conflicts=True,
        )

        row = await BulkPgObject.objects.get(id="keep")
        self.assertEqual(row.name, "first")
        self.assertEqual(await BulkPgObject.objects.count(), 1)

    async def test_bulk_create_empty_list(self):
        result = await BulkPgObject.objects.bulk_create([])
        self.assertEqual(result, [])
        self.assertEqual(await BulkPgObject.objects.count(), 0)

    # ---- bulk_update ----

    async def test_bulk_update_changes_fields(self):
        objs = [self._make(id=f"u-{i:03d}", key=f"k{i}", name=f"n{i}", kind="a", meta={"n": i})
                for i in range(50)]
        await BulkPgObject.objects.bulk_create(objs)

        for obj in objs:
            obj.name = f"updated-{obj.id}"
            obj.kind = "b"

        changed = await BulkPgObject.objects.bulk_update(objs, fields=["name", "kind"])
        self.assertEqual(changed, 50)

        reloaded = await BulkPgObject.objects.get(id="u-010")
        self.assertEqual(reloaded.name, "updated-u-010")
        self.assertEqual(reloaded.kind, "b")
        self.assertEqual(reloaded.meta, {"n": 10})

    async def test_bulk_update_batches(self):
        objs = [self._make(id=f"b-{i:05d}", key=f"k{i}", name="orig") for i in range(1500)]
        await BulkPgObject.objects.bulk_create(objs)

        for obj in objs:
            obj.name = "mass-updated"

        changed = await BulkPgObject.objects.bulk_update(objs, fields=["name"], batch_size=500)
        self.assertEqual(changed, 1500)

        sample = await BulkPgObject.objects.get(id="b-01234")
        self.assertEqual(sample.name, "mass-updated")

    async def test_bulk_update_rejects_empty_fields(self):
        with self.assertRaises(ValueError):
            await BulkPgObject.objects.bulk_update([self._make(id="x", key="k")], fields=[])

    async def test_bulk_update_empty_objs(self):
        changed = await BulkPgObject.objects.bulk_update([], fields=["name"])
        self.assertEqual(changed, 0)
        self.assertEqual(await BulkPgObject.objects.count(), 0)

    # ---- bulk_delete ----

    async def test_bulk_delete_by_instances(self):
        objs = [self._make(id=f"d-{i:03d}", key=f"k{i}") for i in range(50)]
        await BulkPgObject.objects.bulk_create(objs)

        deleted = await BulkPgObject.objects.bulk_delete(objs)
        self.assertEqual(deleted, 50)
        self.assertEqual(await BulkPgObject.objects.count(), 0)

    async def test_bulk_delete_by_pks(self):
        objs = [self._make(id=f"p-{i:03d}", key=f"k{i}") for i in range(50)]
        await BulkPgObject.objects.bulk_create(objs)

        deleted = await BulkPgObject.objects.bulk_delete([o.id for o in objs])
        self.assertEqual(deleted, 50)
        self.assertEqual(await BulkPgObject.objects.count(), 0)

    async def test_bulk_delete_partial(self):
        objs = [self._make(id=f"part-{i:03d}", key=f"k{i}") for i in range(50)]
        await BulkPgObject.objects.bulk_create(objs)

        deleted = await BulkPgObject.objects.bulk_delete(objs[:20])
        self.assertEqual(deleted, 20)
        self.assertEqual(await BulkPgObject.objects.count(), 30)

        surviving = await BulkPgObject.objects.values_list("id", flat=True)
        surviving = sorted(list(surviving))
        expected = sorted([f"part-{i:03d}" for i in range(20, 50)])
        self.assertEqual(surviving, expected)

    async def test_bulk_delete_batches(self):
        objs = [self._make(id=f"m-{i:05d}", key=f"k{i}") for i in range(1500)]
        await BulkPgObject.objects.bulk_create(objs)

        deleted = await BulkPgObject.objects.bulk_delete(objs, batch_size=500)
        self.assertEqual(deleted, 1500)
        self.assertEqual(await BulkPgObject.objects.count(), 0)

    async def test_bulk_delete_empty_list(self):
        await BulkPgObject.objects.bulk_create([self._make(id="stay", key="k")])
        deleted = await BulkPgObject.objects.bulk_delete([])
        self.assertEqual(deleted, 0)
        self.assertEqual(await BulkPgObject.objects.count(), 1)


if __name__ == "__main__":
    unittest.main()
