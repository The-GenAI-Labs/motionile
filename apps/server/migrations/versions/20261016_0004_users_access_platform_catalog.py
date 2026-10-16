from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def timestamps() -> list[sa.Column[datetime]]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "permissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "key ~ '^[a-z][a-z_]*(\\.[a-z][a-z_]*)+$' AND char_length(key) <= 80",
            name=op.f("ck_permissions_key_format"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_permissions")),
        sa.UniqueConstraint("key", name=op.f("uq_permissions_key")),
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["permissions.id"],
            name=op.f("fk_role_permissions_permission_id_permissions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name=op.f("fk_role_permissions_role_id_roles"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name=op.f("pk_role_permissions")),
    )
    op.create_index(op.f("ix_role_permissions_permission_id"), "role_permissions", ["permission_id"])
    op.create_table(
        "user_preferences",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("default_style", sa.Text(), nullable=True),
        sa.Column("pace", sa.Text(), server_default="normal", nullable=False),
        sa.Column("language", sa.Text(), server_default="en", nullable=False),
        sa.Column("depth", sa.Text(), server_default="standard", nullable=False),
        sa.Column("default_voice_id", sa.Uuid(), nullable=True),
        sa.Column("default_aspect", sa.Text(), server_default="16:9", nullable=False),
        sa.Column("captions_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *timestamps(),
        sa.CheckConstraint("pace IN ('slow', 'normal', 'fast')", name=op.f("ck_user_preferences_pace")),
        sa.CheckConstraint("depth IN ('overview', 'standard', 'deep')", name=op.f("ck_user_preferences_depth")),
        sa.CheckConstraint(
            "default_aspect IN ('16:9', '9:16', '1:1')", name=op.f("ck_user_preferences_default_aspect")
        ),
        sa.CheckConstraint("language ~ '^[a-z]{2,3}(-[A-Z]{2})?$'", name=op.f("ck_user_preferences_language_format")),
        sa.CheckConstraint(
            "default_style IS NULL OR default_style ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
            name=op.f("ck_user_preferences_default_style_format"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_preferences_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_preferences")),
    )
    op.create_index(op.f("ix_user_preferences_default_voice_id"), "user_preferences", ["default_voice_id"])
    op.create_table(
        "system_settings",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "key ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$'", name=op.f("ck_system_settings_key_format")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_system_settings_version_positive")),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=op.f("fk_system_settings_updated_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_system_settings")),
    )
    op.create_index(op.f("ix_system_settings_updated_by"), "system_settings", ["updated_by"])
    op.create_table(
        "feature_flags",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("rollout_percentage", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column(
            "rules", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        *timestamps(),
        sa.CheckConstraint("key ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$'", name=op.f("ck_feature_flags_key_format")),
        sa.CheckConstraint(
            "rollout_percentage BETWEEN 0 AND 100", name=op.f("ck_feature_flags_rollout_percentage_range")
        ),
        sa.CheckConstraint("jsonb_typeof(rules) = 'array'", name=op.f("ck_feature_flags_rules_array")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_feature_flags_version_positive")),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=op.f("fk_feature_flags_updated_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_feature_flags")),
    )
    op.create_index(op.f("ix_feature_flags_updated_by"), "feature_flags", ["updated_by"])
    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("seo_title", sa.Text(), nullable=True),
        sa.Column("seo_description", sa.Text(), nullable=True),
        *timestamps(),
        sa.CheckConstraint("level IN ('category', 'subcategory')", name=op.f("ck_categories_level")),
        sa.CheckConstraint(
            "(level = 'category' AND parent_id IS NULL) OR (level = 'subcategory' AND parent_id IS NOT NULL)",
            name=op.f("ck_categories_level_parent"),
        ),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND char_length(slug) <= 80",
            name=op.f("ck_categories_slug_format"),
        ),
        sa.CheckConstraint("parent_id IS NULL OR parent_id <> id", name=op.f("ck_categories_not_own_parent")),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 80", name=op.f("ck_categories_name_length")),
        sa.CheckConstraint(
            "description IS NULL OR char_length(description) <= 500", name=op.f("ck_categories_description_length")
        ),
        sa.CheckConstraint(
            "seo_title IS NULL OR char_length(seo_title) <= 70", name=op.f("ck_categories_seo_title_length")
        ),
        sa.CheckConstraint(
            "seo_description IS NULL OR char_length(seo_description) <= 160",
            name=op.f("ck_categories_seo_description_length"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_categories_version_positive")),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["categories.id"], name=op.f("fk_categories_parent_id_categories"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint(
            "parent_id", "slug", name=op.f("uq_categories_parent_id_slug"), postgresql_nulls_not_distinct=True
        ),
    )
    op.create_index(
        op.f("ix_categories_parent_id_sort_order"),
        "categories",
        ["parent_id", "sort_order"],
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "topics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("suggested_duration_ms", sa.Integer(), server_default="60000", nullable=False),
        sa.Column("difficulty", sa.Text(), server_default="beginner", nullable=False),
        sa.Column("skill_hints", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("seo_title", sa.Text(), nullable=True),
        sa.Column("seo_description", sa.Text(), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND char_length(slug) <= 120",
            name=op.f("ck_topics_slug_format"),
        ),
        sa.CheckConstraint(
            "suggested_duration_ms BETWEEN 10000 AND 120000", name=op.f("ck_topics_suggested_duration_ms_range")
        ),
        sa.CheckConstraint("difficulty IN ('beginner', 'intermediate', 'advanced')", name=op.f("ck_topics_difficulty")),
        sa.CheckConstraint("char_length(title) BETWEEN 1 AND 120", name=op.f("ck_topics_title_length")),
        sa.CheckConstraint("summary IS NULL OR char_length(summary) <= 500", name=op.f("ck_topics_summary_length")),
        sa.CheckConstraint(
            "seo_title IS NULL OR char_length(seo_title) <= 70", name=op.f("ck_topics_seo_title_length")
        ),
        sa.CheckConstraint(
            "seo_description IS NULL OR char_length(seo_description) <= 160",
            name=op.f("ck_topics_seo_description_length"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_topics_version_positive")),
        sa.ForeignKeyConstraint(
            ["category_id"], ["categories.id"], name=op.f("fk_topics_category_id_categories"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_topics")),
        sa.UniqueConstraint("category_id", "slug", name=op.f("uq_topics_category_id_slug")),
    )
    op.create_index(
        op.f("ix_topics_category_id_sort_order"),
        "topics",
        ["category_id", "sort_order"],
        postgresql_where=sa.text("is_active"),
    )
    op.create_index(
        op.f("ix_topics_title_trgm"),
        "topics",
        ["title"],
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.create_index(
        op.f("ix_topics_summary_trgm"),
        "topics",
        ["summary"],
        postgresql_using="gin",
        postgresql_ops={"summary": "gin_trgm_ops"},
    )
    op.create_table(
        "catalog_slug_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("old_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "entity_type IN ('category', 'subcategory', 'topic')",
            name=op.f("ck_catalog_slug_history_entity_type"),
        ),
        sa.CheckConstraint(
            "old_path ~ '^/explore/[a-z0-9]+(-[a-z0-9]+)*(/[a-z0-9]+(-[a-z0-9]+)*){0,2}$'",
            name=op.f("ck_catalog_slug_history_old_path"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_slug_history")),
        sa.UniqueConstraint("old_path", name=op.f("uq_catalog_slug_history_old_path")),
    )
    op.create_index(op.f("ix_catalog_slug_history_entity"), "catalog_slug_history", ["entity_type", "entity_id"])
    permission_table = sa.table(
        "permissions",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.Text()),
        sa.column("description", sa.Text()),
    )
    permission_values = (
        ("users.read", "Read users and their administrative details"),
        ("users.manage", "Suspend, restore and sign out users"),
        ("users.roles.assign", "Assign roles to users"),
        ("roles.read", "Read roles and permissions"),
        ("roles.manage", "Create, edit and delete roles"),
        ("audit.read", "Read audit entries"),
        ("analytics.read", "Read administrative analytics"),
        ("settings.read", "Read private system settings"),
        ("settings.manage", "Update system settings"),
        ("flags.manage", "Manage feature flags"),
        ("catalog.manage", "Manage categories and topics"),
    )
    op.bulk_insert(
        permission_table,
        [
            {
                "id": UUID(f"0199eb00-0000-7000-8000-{index:012d}"),
                "key": key,
                "description": description,
            }
            for index, (key, description) in enumerate(permission_values, start=1)
        ],
    )
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT roles.id, permissions.id FROM roles CROSS JOIN permissions "
        "WHERE roles.key = 'admin' AND permissions.key NOT IN ('roles.manage', 'settings.manage')"
    )


def downgrade() -> None:
    op.drop_table("catalog_slug_history")
    op.drop_table("topics")
    op.drop_table("categories")
    op.drop_table("feature_flags")
    op.drop_table("system_settings")
    op.drop_table("user_preferences")
    op.drop_table("role_permissions")
    op.drop_table("permissions")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
