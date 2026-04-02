# NeutronAPI Core Module Audit

This audit covers every non-test Python module under `neutronapi/` as of this sweep.

Verification completed:
- `source venv/bin/activate && python manage.py test`
- Result: `297` tests passed, `26` skipped
- Targeted regression runs for ORM/custom primary keys, queryset ordering, background scheduling, parsers, and command scaffolding

Repo hygiene completed:
- Local `origin` updated to `https://github.com/aaronkazah/neutronapi.git`
- `pyproject.toml` now publishes `Homepage` and `Repository` for `aaronkazah/neutronapi`
- Root sample fixture app `apps/test_command` removed from the tracked tree

Notes:
- User-facing `print()` output remains in management commands and migration/test runners where console output is the contract.
- Hot-path runtime `print()` calls were removed from request handling, parsing, and background scheduling.

## Root package

- `neutronapi/__init__.py` - changed; lazy export path retained and rechecked against CLI/cold-start flows.
- `neutronapi/__main__.py` - certified as-is; verified by `python -m neutronapi` cold-start tests.
- `neutronapi/application.py` - changed; reviewed for API registration, reverse lookup, websocket routing, and middleware binding. Covered by `neutronapi/tests/test_application.py`, `neutronapi/tests/test_application_api_registration.py`, `neutronapi/tests/test_application_routing.py`, `neutronapi/tests/test_reverse.py`, `neutronapi/tests/test_websocket.py`, `neutronapi/tests/test_websocket_concurrent.py`, `neutronapi/tests/test_parsers_and_middleware.py`.
- `neutronapi/background.py` - changed; reviewed for scheduler timing, weekly cadence, poll interval, and shutdown semantics. Covered by `neutronapi/tests/test_background.py`.
- `neutronapi/base.py` - changed; reviewed for endpoint registration, request parsing, auth/permission/throttle flow, websocket send/receive, and response serialization. Covered by `neutronapi/tests/test_application.py`, `neutronapi/tests/test_parsers_and_middleware.py`, `neutronapi/tests/test_websocket.py`, `neutronapi/tests/test_websocket_concurrent.py`.
- `neutronapi/cli.py` - certified as-is after prior cold-start overhaul; verified by `neutronapi/tests/commands/test_cold_start_integration.py`, `neutronapi/tests/commands/test_commands.py`, `neutronapi/tests/commands/test_custom_commands.py`.
- `neutronapi/command_discovery.py` - certified as-is; reviewed for deterministic import error collection and custom-command discovery. Covered by `neutronapi/tests/commands/test_custom_commands.py`, `neutronapi/tests/commands/test_commands.py`.
- `neutronapi/conf.py` - changed; reviewed for lazy settings setup, development fallback, and entry loading. Covered by `neutronapi/tests/commands/test_cold_start_integration.py`, `neutronapi/tests/commands/test_checks.py`, `neutronapi/tests/commands/test_commands.py`.
- `neutronapi/diagnostics.py` - certified as-is after prior check-system work; reviewed for project file checks, settings import checks, entry import checks, and custom command import checks. Covered by `neutronapi/tests/commands/test_checks.py`, `neutronapi/tests/commands/test_cold_start_integration.py`.
- `neutronapi/encoders.py` - changed; reviewed for `orjson` serialization and framework object encoding. Covered by `neutronapi/tests/test_encoders.py`, `neutronapi/tests/test_parsers_and_middleware.py`.
- `neutronapi/exceptions.py` - certified as-is; reviewed as explicit framework exception surface. Covered indirectly by command, middleware, and DB tests.
- `neutronapi/http.py` - certified as-is; reviewed as status enum only. Covered indirectly by response and API tests.
- `neutronapi/parsers.py` - changed; reviewed for JSON/form/binary/multipart parsing, including replacement of deprecated `cgi.FieldStorage`. Covered by `neutronapi/tests/test_parsers_and_middleware.py`.
- `neutronapi/scaffold.py` - certified as-is after prior scaffold overhaul; reviewed for canonical file generation, repair behavior, and destination validation. Covered by `neutronapi/tests/commands/test_commands.py`, `neutronapi/tests/commands/test_cold_start_integration.py`.

## API package

- `neutronapi/api/__init__.py` - certified as-is; no behavior beyond package marker.
- `neutronapi/api/exceptions.py` - certified as-is; reviewed as stable HTTP/API exception surface. Covered indirectly by application and middleware tests.

## Authentication package

- `neutronapi/authentication/__init__.py` - certified as-is; export-only module.
- `neutronapi/authentication/base.py` - certified as-is; reviewed as current auth contract surface. Covered by `neutronapi/tests/authentication/test_authentication.py`.
- `neutronapi/authentication/exceptions.py` - certified as-is; explicit exception surface only.

## Commands

- `neutronapi/commands/__init__.py` - certified as-is; package marker.
- `neutronapi/commands/base.py` - certified as-is; reviewed as the shared custom-command base used by command discovery tests. Covered by `neutronapi/tests/commands/test_custom_commands.py`.
- `neutronapi/commands/check.py` - certified as-is; reviewed for check command dispatch and quiet mode. Covered by `neutronapi/tests/commands/test_checks.py`.
- `neutronapi/commands/makemigrations.py` - changed; reviewed for settings/runtime usage and migration generation entry flow. Covered by `neutronapi/tests/db/test_migrations.py`, `neutronapi/tests/db/test_migrations_edge_cases.py`, `neutronapi/tests/db/test_migrations_field_renames.py`, `neutronapi/tests/db/test_migrations_simple.py`.
- `neutronapi/commands/migrate.py` - changed; reviewed for settings/runtime access and per-database migration application flow. Covered by `neutronapi/tests/db/test_migrations.py`, `neutronapi/tests/db/test_migration_tracker_flow.py`, `neutronapi/tests/commands/test_cli_migrations_integration.py`.
- `neutronapi/commands/shell.py` - certified as-is; reviewed for shell bootstrap behavior and project import setup.
- `neutronapi/commands/start.py` - changed; reviewed for server startup, preflight checks, reload behavior, and settings access. Covered by `neutronapi/tests/commands/test_cold_start_integration.py`, `neutronapi/tests/commands/test_commands.py`.
- `neutronapi/commands/startapp.py` - certified as-is after scaffold overhaul; reviewed for app creation/repair behavior. Covered by `neutronapi/tests/commands/test_commands.py`.
- `neutronapi/commands/startproject.py` - certified as-is after scaffold overhaul; reviewed for project creation/repair behavior. Covered by `neutronapi/tests/commands/test_commands.py`, `neutronapi/tests/commands/test_cold_start_integration.py`.
- `neutronapi/commands/test.py` - certified as-is; reviewed for framework test runner semantics because `python manage.py test` remains the supported path. Covered by the full framework suite and command-runner tests.

## Database package

- `neutronapi/db/__init__.py` - changed; reviewed for live `CONNECTIONS` export and shutdown behavior. Covered by `neutronapi/tests/db/test_db.py`.
- `neutronapi/db/connection.py` - changed; reviewed for explicit settings-backed connection lifecycle and shutdown behavior. Covered by `neutronapi/tests/db/test_db.py`, `neutronapi/tests/db/test_migrations_postgres.py`, `neutronapi/tests/db/test_queryset_postgres.py`.
- `neutronapi/db/exceptions.py` - certified as-is; explicit DB exception surface only.
- `neutronapi/db/fields.py` - certified as-is; reviewed for conversion/serialization behavior against the existing field contract. Covered by `neutronapi/tests/db/test_db.py`, `neutronapi/tests/db/test_json_filtering.py`, `neutronapi/tests/db/test_fields_as_fieldname.py`.
- `neutronapi/db/migration_tracker.py` - certified as-is; reviewed for migration tracking and application order. Covered by `neutronapi/tests/db/test_migration_tracker_flow.py`, `neutronapi/tests/db/test_migrations.py`.
- `neutronapi/db/migrations.py` - certified as-is; reviewed for migration loading, planning, hash state, and application flow. Covered by `neutronapi/tests/db/test_migrations.py`, `neutronapi/tests/db/test_migrations_edge_cases.py`, `neutronapi/tests/db/test_migrations_field_renames.py`, `neutronapi/tests/db/test_migrations_simple.py`, `neutronapi/tests/db/test_migrations_postgres.py`, `neutronapi/tests/commands/test_cli_migrations_integration.py`.
- `neutronapi/db/models.py` - changed; reviewed for default PK generation, custom PK handling, save/update/delete semantics, refresh, and table naming. Covered by `neutronapi/tests/db/test_pk_id_consistency.py`, `neutronapi/tests/db/test_auto_pk_generation.py`, `neutronapi/tests/db/test_auto_save_without_create_flag.py`, `neutronapi/tests/db/test_db.py`, `neutronapi/tests/db/test_model_save_semantics.py`, `neutronapi/tests/db/test_models.py`, `neutronapi/tests/db/test_organization_save_pattern.py`.
- `neutronapi/db/queryset.py` - changed; reviewed for `last()`, explicit ordering reversal, result materialization, filtering, values/exclude, and async fetch flow. Covered by `neutronapi/tests/db/test_queryset.py`, `neutronapi/tests/db/test_queryset_await.py`, `neutronapi/tests/db/test_queryset_more.py`, `neutronapi/tests/db/test_queryset_postgres.py`, `neutronapi/tests/db/test_json_filtering.py`.

## Database providers

- `neutronapi/db/providers/__init__.py` - certified as-is; provider export module.
- `neutronapi/db/providers/base.py` - certified as-is; abstract provider contract reviewed against sqlite/postgres implementations.
- `neutronapi/db/providers/postgres.py` - certified as-is; reviewed for SQL generation and serialization paths. Covered by `neutronapi/tests/db/test_migrations_postgres.py`, `neutronapi/tests/db/test_migrations_fts_postgres.py`, `neutronapi/tests/db/test_queryset_postgres.py`, `neutronapi/tests/db/test_search_postgres.py`.
- `neutronapi/db/providers/sqlite.py` - certified as-is; reviewed for SQL generation, serialization, and JSON behavior. Covered by `neutronapi/tests/db/test_db.py`, `neutronapi/tests/db/test_json_filtering.py`, `neutronapi/tests/db/test_migrations_fts_sqlite.py`, `neutronapi/tests/db/test_migrations_fts_sqlite_default.py`, `neutronapi/tests/db/test_search_sqlite.py`.

## Middleware

- `neutronapi/middleware/__init__.py` - certified as-is; package/export module.
- `neutronapi/middleware/allowed_hosts.py` - changed; reviewed to remove direct project imports and to rely on framework settings/config only. Covered by `neutronapi/tests/middleware/test_middleware.py`.
- `neutronapi/middleware/compression.py` - certified as-is; reviewed for gzip/brotli response compression behavior. Covered by `neutronapi/tests/middleware/test_middleware.py`, `neutronapi/tests/test_parsers_and_middleware.py`.
- `neutronapi/middleware/cors.py` - certified as-is; reviewed for origin validation and wildcard behavior. Covered by `neutronapi/tests/middleware/test_middleware.py`.
- `neutronapi/middleware/exceptions.py` - certified as-is; explicit middleware exception surface only.
- `neutronapi/middleware/routing.py` - changed; reviewed to remove implicit `apps.tasks` startup fallback and to keep startup/shutdown handling deterministic. Covered by `neutronapi/tests/test_application_routing.py`, `neutronapi/tests/test_background.py`.

## OpenAPI

- `neutronapi/openapi/__init__.py` - certified as-is; package/export module.
- `neutronapi/openapi/exceptions.py` - certified as-is; explicit exception surface only.
- `neutronapi/openapi/openapi.py` - changed; reviewed for current `Application` references and schema generation entry points. Covered by `neutronapi/tests/openapi/test_openapi.py`.
- `neutronapi/openapi/swagger.py` - certified as-is; reviewed as Swagger UI/schema presentation helper. Covered by `neutronapi/tests/openapi/test_openapi.py`.

## Utilities

- `neutronapi/utils/__init__.py` - certified as-is; package marker.
- `neutronapi/utils/ids.py` - certified as-is; reviewed for ULID/UUIDv7 ID generation fallback used by model PK generation. Covered by `neutronapi/tests/db/test_auto_save_without_create_flag.py`, `neutronapi/tests/db/test_pk_id_consistency.py`.

## Certification outcome

All `53` non-test modules were explicitly accounted for in this audit and validated against the current framework behavior.
