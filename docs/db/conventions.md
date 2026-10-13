# Database conventions

These conventions apply to every table, migration and query. The full schema blueprint arrives in Phase 2.

## Engine and access

- PostgreSQL 17 with the `vector`, `citext` and `pgcrypto` extensions, enabled by the first migration.
- Local development runs Postgres with pgvector in Docker. Staging and production use Neon or RDS, selected only by `DATABASE_URL`.
- `DATABASE_URL` is the application connection and may go through a pooler. `DATABASE_DIRECT_URL`, when set, is a direct connection used by migrations and procrastinate workers.
- The application uses SQLAlchemy 2 async with asyncpg. Migrations run through Alembic with psycopg.

## Keys and timestamps

- Primary keys are UUIDv7, generated in the application with `uuid_utils.uuid7()`.
- Every table has `created_at` and `updated_at` as `timestamptz` in UTC.
- Soft delete with `deleted_at` exists only on `users` and `skills`. Every other table deletes rows.

## Types

- Statuses are `text` with a named `CHECK` constraint listing the allowed values. Native Postgres enums are not used.
- Money is `bigint` in paise. Credits are `bigint`.
- Case-insensitive identifiers such as emails use `citext`.
- `jsonb` holds payloads and metadata only, never fields that queries filter or join on.

## Constraints and indexes

The SQLAlchemy metadata in `motionile.core.db` applies this naming convention:

| Kind        | Pattern                                 |
| ----------- | --------------------------------------- |
| Index       | `ix_<table>_<columns>`                  |
| Unique      | `uq_<table>_<columns>`                  |
| Check       | `ck_<table>_<name>`                     |
| Foreign key | `fk_<table>_<columns>_<referred_table>` |
| Primary key | `pk_<table>`                            |

- Every foreign key has an index.
- `ON DELETE` is chosen explicitly for every foreign key: `CASCADE` for owned children, `RESTRICT` for references that must outlive the parent, `SET NULL` only for optional links.

## Migrations

- One migration per pull request at most.
- Every migration is reversible: `downgrade()` undoes `upgrade()` completely.
- Changes follow expand and contract, so a code rollback never breaks the schema:
  1. Expand: add new tables, nullable columns or new indexes. Deploy code that writes both shapes.
  2. Backfill in a task, not in the migration, when the data is large.
  3. Contract in a later pull request: drop what no deployed code reads.
- Migrations contain no comments and no application imports beyond `motionile.core`.
- An integration test proves every migration upgrades, downgrades and upgrades again against the pgvector image.

## Queries

- Repositories hold all SQL. Services never build queries.
- Every lookup of a user-owned resource filters by the owner.
- Lists use cursor pagination on a stable, indexed ordering.
