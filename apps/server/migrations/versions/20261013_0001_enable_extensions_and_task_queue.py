"""Enable Postgres extensions and install the procrastinate task queue schema.

Revision ID: 0001
Revises:
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op
from procrastinate.schema import SchemaManager

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXTENSIONS = ("vector", "citext", "pgcrypto")

DROP_TASK_QUEUE_SCHEMA = """
DO $drop$
DECLARE
    target record;
BEGIN
    FOR target IN
        SELECT tablename FROM pg_tables
        WHERE schemaname = current_schema() AND tablename LIKE 'procrastinate\\_%'
    LOOP
        EXECUTE format('DROP TABLE IF EXISTS %I CASCADE', target.tablename);
    END LOOP;
    FOR target IN
        SELECT p.oid::regprocedure AS signature FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = current_schema() AND p.proname LIKE 'procrastinate\\_%'
    LOOP
        EXECUTE format('DROP FUNCTION IF EXISTS %s CASCADE', target.signature);
    END LOOP;
    FOR target IN
        SELECT t.typname FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = current_schema() AND t.typname LIKE 'procrastinate\\_%' AND t.typtype IN ('e', 'c')
    LOOP
        EXECUTE format('DROP TYPE IF EXISTS %I CASCADE', target.typname);
    END LOOP;
END
$drop$;
"""


def upgrade() -> None:
    for extension in EXTENSIONS:
        op.execute(f'CREATE EXTENSION IF NOT EXISTS "{extension}"')
    op.execute(SchemaManager.get_schema())


def downgrade() -> None:
    op.execute(DROP_TASK_QUEUE_SCHEMA)
    for extension in reversed(EXTENSIONS):
        op.execute(f'DROP EXTENSION IF EXISTS "{extension}"')
