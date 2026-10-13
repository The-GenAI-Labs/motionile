# Database conventions

These conventions apply to every table, migration and query. The full design of every table lives in [`schema.md`](schema.md); diagrams in [`erd.md`](erd.md); status transitions in [`state-machines.md`](state-machines.md); purge rules in [`retention.md`](retention.md).

## Engine and access

- PostgreSQL 17 with the `vector`, `citext` and `pgcrypto` extensions, enabled by the first migration.
- Local development runs Postgres with pgvector in Docker. Staging and production use Neon or RDS, selected only by `DATABASE_URL`.
- `DATABASE_URL` is the application connection and may go through a pooler. `DATABASE_DIRECT_URL`, when set, is a direct connection used by migrations and procrastinate workers.
- The application uses SQLAlchemy 2 async with asyncpg through `motionile.core.db`. When `DATABASE_URL` goes through a transaction pooler, set `DATABASE_STATEMENT_CACHE_SIZE=0` to disable asyncpg's prepared statement cache.
- Migrations run through Alembic with psycopg on the direct connection.

## Schemas

- Application tables live in `public`.
- procrastinate keeps its tables in its default schema (`public`, every object prefixed `procrastinate_`).
- LangGraph checkpoints live in the `langgraph` schema, created by the Phase 9 migration.

## Keys and timestamps

- Primary keys are UUIDv7 generated in the application by `motionile.core.ids.new_id()`. There is no database default.
- Configuration tables keyed by a stable string that code refers to (`system_settings.key`, `feature_flags.key`, `platform_specs.platform`) use that string as the primary key.
- One-to-one tables (`credentials`, `credit_wallets`, `user_preferences`, `billing_customers`, `account_credentials`, `skill_embeddings`) use the owner's ID as their primary key.
- Every mutable table has `created_at` and `updated_at`, both `timestamptz NOT NULL DEFAULT now()`. `updated_at` is maintained by the ORM through `TimestampMixin`.
- Append-only tables (`audit_log`, `credit_ledger`, `usage_records`, `job_events`) have `created_at` only. Application code never updates or deletes their rows; the `forbid_append_only_mutation()` trigger enforces it, allowing only referential actions and the retention job.
- Association tables (`user_roles`, `role_permissions`, `job_skills`) are insert and delete only and have only a creation timestamp.

## Soft delete

- Only `users` and `skills` have `deleted_at`. Every other table deletes rows.
- Uniqueness on soft-deleted tables uses partial unique indexes `WHERE deleted_at IS NULL`, so a deleted row never blocks a new one.
- Repositories filter `deleted_at IS NULL` by default; reading deleted rows is explicit.

## Types

| Value                  | Type                                                                                       |
| ---------------------- | ------------------------------------------------------------------------------------------ |
| Status                 | `text` with a named `CHECK` listing the allowed values; no native enums                    |
| Money                  | `bigint` in paise, with `currency char(3)` (ISO 4217)                                      |
| Credits                | `bigint`                                                                                   |
| Durations              | `integer` milliseconds, columns suffixed `_ms`                                             |
| Sizes                  | `bigint` bytes, columns suffixed `_bytes`                                                  |
| Provider cost          | `bigint` micro-dollars, column suffixed `_micros_usd`                                      |
| Email                  | `citext`                                                                                   |
| Phone                  | `text` (or `citext` when shared with emails) in E.164, checked with `^\+[1-9][0-9]{6,14}$` |
| IP address             | `inet`                                                                                     |
| Hashes and secrets     | `bytea` with an `octet_length` check (32 for SHA-256)                                      |
| Timestamps             | `timestamptz`, always UTC in the application                                               |
| Embeddings             | `vector(D)` with `D` from `EMBEDDING_DIMENSIONS` (default 1536), plus a `model` column     |
| Lists of simple values | `text[]`                                                                                   |
| Payloads and metadata  | `jsonb` with a `jsonb_typeof` check; never filtered or joined on                           |

- Text columns that users or providers fill have a `char_length` check.
- Composite uniqueness that includes a nullable column uses `NULLS NOT DISTINCT`.

## Embeddings

- Every embedding column sits beside a `model` column naming the model that produced it.
- Indexes are HNSW with `vector_cosine_ops`, `m = 16`, `ef_construction = 64`. Queries use cosine distance (`<=>`).
- Changing the embedding model means re-embedding every row; rows are found by `model`. Changing the dimension needs a migration.

## Constraints and indexes

The SQLAlchemy metadata in `motionile.core.db` applies this naming convention, and hand-written constraints follow it too:

| Kind        | Pattern                                 |
| ----------- | --------------------------------------- |
| Index       | `ix_<table>_<columns>`                  |
| Unique      | `uq_<table>_<columns>`                  |
| Check       | `ck_<table>_<name>`                     |
| Foreign key | `fk_<table>_<columns>_<referred_table>` |
| Primary key | `pk_<table>`                            |
| Trigger     | `trg_<table>_<purpose>`                 |

- Every foreign key column is indexed, alone or as the leading column of another index.
- `ON DELETE` is chosen explicitly for every foreign key:
  - `CASCADE` for owned children.
  - `RESTRICT` for references that must outlive the parent, including every billing reference to `users`.
  - `SET NULL` only for optional links.
  - `NO ACTION` where a reference must block deleting its target on its own, but both rows may be removed by the same cascading delete (for example a user deletion that reaches an asset and the row using it through two paths).
- Circular foreign keys (`skills.current_version_id`, `prompt_templates.active_version_id`) are created with `use_alter=True` and are `DEFERRABLE INITIALLY DEFERRED`.
- A foreign key to a table created by a later phase is added by that phase's migration; until then the column exists without the constraint.
- Every index in `schema.md` names the query it serves.

## Migrations

- One migration per pull request at most.
- Every migration is reversible: `downgrade()` undoes `upgrade()` completely.
- A migration creates tables exactly as `schema.md` defines them. A change to a table updates `schema.md` in the same pull request.
- Changes follow expand and contract, so a code rollback never breaks the schema:
  1. Expand: add new tables, nullable columns or new indexes. Deploy code that writes both shapes.
  2. Backfill in a task, not in the migration, when the data is large.
  3. Contract in a later pull request: drop what no deployed code reads.
- Indexes on large existing tables are created `CONCURRENTLY` in their own migration with `autocommit_block()`.
- Migrations contain no comments and no application imports beyond `motionile.core`.
- An integration test proves the migration chain upgrades to head and downgrades to base on a fresh container, and checks the created objects against `schema.md`.

## Queries

- Repositories hold all SQL. Services never build queries.
- Every lookup of a user-owned resource filters by the owner.
- Lists use keyset pagination on `(created_at, id)` with opaque, signed cursors from `motionile.core.pagination`.
- Transactions are opened by services through the unit-of-work helper; repositories never commit.
