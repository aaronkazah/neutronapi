import asyncio


def _table_base_from_full(app_label: str, full_table_name: str) -> str:
    prefix = f"{app_label}_"
    return full_table_name[len(prefix):] if full_table_name.startswith(prefix) else full_table_name


async def table_exists(connection, provider, app_label: str, full_table_name: str) -> bool:
    """Provider-aware table existence check.

    For SQLite, uses sqlite_master. For Postgres, uses provider.table_exists(schema.table).
    """
    db_type = getattr(connection, 'db_type', None)
    if str(db_type).lower().endswith('postgres'):
        base = _table_base_from_full(app_label, full_table_name)
        return await provider.table_exists(f"{app_label}.{base}")
    else:
        cursor = await connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (full_table_name,),
        )
        result = await cursor.fetchone()
        await cursor.close()
        return result is not None


async def get_columns_dict(connection, provider, app_label: str, full_table_name: str) -> dict:
    """Return a dict of {column_name: column_type} for a given table, provider-aware."""
    db_type = getattr(connection, 'db_type', None)
    if str(db_type).lower().endswith('postgres'):
        base = _table_base_from_full(app_label, full_table_name)
        info = await provider.get_column_info(app_label, base)
        return {col['name']: str(col['type']).upper() for col in info}
    else:
        cursor = await connection.execute(f"PRAGMA table_info({full_table_name})")
        columns = await cursor.fetchall()
        await cursor.close()
        return {col[1]: col[2] for col in columns}
