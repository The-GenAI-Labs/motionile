from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE users ( "
        "        name TEXT,  "
        "        status TEXT DEFAULT 'pending_verification' NOT NULL,  "
        "        avatar_storage_key TEXT,  "
        "        locale TEXT DEFAULT 'en-IN' NOT NULL,  "
        "        last_login_at TIMESTAMP WITH TIME ZONE,  "
        "        id UUID NOT NULL,  "
        "        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,  "
        "        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,  "
        "        deleted_at TIMESTAMP WITH TIME ZONE,  "
        "        CONSTRAINT pk_users PRIMARY KEY (id),  "
        "        CONSTRAINT ck_users_status CHECK (status IN ('pending_verification', 'active',  "
        "'suspended', 'deleted')),  "
        "        CONSTRAINT ck_users_deleted_consistent CHECK ((status = 'deleted') = (deleted_at  "
        "IS NOT NULL)),  "
        "        CONSTRAINT ck_users_name_length CHECK (name IS NULL OR char_length(name) BETWEEN 1 "
        " AND 120),  "
        "        CONSTRAINT ck_users_avatar_storage_key_length CHECK (avatar_storage_key IS NULL OR "
        " char_length(avatar_storage_key) <= 512),  "
        "        CONSTRAINT ck_users_locale_format CHECK (locale ~ '^[a-z]{2,3}(-[A-Z]{2})?$') "
        ") "
    )
    op.execute("CREATE INDEX ix_users_created_at_id ON users (created_at, id) WHERE deleted_at IS NULL")
    op.execute("CREATE INDEX ix_users_deleted_at ON users (deleted_at) WHERE deleted_at IS NOT NULL")
    op.execute("CREATE INDEX ix_users_status_created_at ON users (status, created_at) WHERE deleted_at IS NULL")
    op.execute(
        "CREATE TABLE user_contacts ( "
        "        user_id UUID NOT NULL,  "
        "        kind TEXT NOT NULL,  "
        "        value CITEXT NOT NULL,  "
        "        verified_at TIMESTAMP WITH TIME ZONE,  "
        "        is_primary BOOLEAN DEFAULT false NOT NULL,  "
        "        id UUID NOT NULL,  "
        "        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,  "
        "        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,  "
        "        CONSTRAINT pk_user_contacts PRIMARY KEY (id),  "
        "        CONSTRAINT uq_user_contacts_user_id_kind_value UNIQUE (user_id, kind, value),  "
        "        CONSTRAINT ck_user_contacts_kind CHECK (kind IN ('email', 'phone')),  "
        "        CONSTRAINT ck_user_contacts_email_format CHECK (kind <> 'email' OR (value ~  "
        "'^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$' AND char_length(value) <= 254)),  "
        "        CONSTRAINT ck_user_contacts_phone_format CHECK (kind <> 'phone' OR value ~  "
        "'^\\+[1-9][0-9]{6,14}$'),  "
        "        CONSTRAINT fk_user_contacts_user_id_users FOREIGN KEY(user_id) REFERENCES users  "
        "(id) ON DELETE CASCADE "
        ") "
    )
    op.execute("CREATE INDEX ix_user_contacts_kind_value ON user_contacts (kind, value)")
    op.execute(
        "CREATE UNIQUE INDEX ix_user_contacts_kind_value_verified ON user_contacts (kind, value) "
        "WHERE verified_at IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_user_contacts_user_id_kind_primary ON user_contacts (user_id, kind) WHERE is_primary"
    )
    op.execute(
        "CREATE TABLE credentials ( "
        "        user_id UUID NOT NULL,  "
        "        password_hash TEXT NOT NULL,  "
        "        password_updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,  "
        "        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,  "
        "        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,  "
        "        CONSTRAINT pk_credentials PRIMARY KEY (user_id),  "
        "        CONSTRAINT ck_credentials_password_hash_argon2id CHECK (password_hash LIKE  "
        "'$argon2id$%'),  "
        "        CONSTRAINT fk_credentials_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) "
        " ON DELETE CASCADE "
        ") "
    )
    op.execute(
        "CREATE TABLE oauth_identities ( "
        "        user_id UUID NOT NULL,  "
        "        provider TEXT NOT NULL,  "
        "        subject TEXT NOT NULL,  "
        "        email CITEXT,  "
        "        email_verified BOOLEAN DEFAULT false NOT NULL,  "
        "        last_login_at TIMESTAMP WITH TIME ZONE,  "
        "        id UUID NOT NULL,  "
        "        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,  "
        "        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,  "
        "        CONSTRAINT pk_oauth_identities PRIMARY KEY (id),  "
        "        CONSTRAINT uq_oauth_identities_provider_subject UNIQUE (provider, subject),  "
        "        CONSTRAINT ck_oauth_identities_provider CHECK (provider IN ('google', 'github',  "
        "'microsoft')),  "
        "        CONSTRAINT ck_oauth_identities_subject_length CHECK (char_length(subject) BETWEEN  "
        "1 AND 255),  "
        "        CONSTRAINT fk_oauth_identities_user_id_users FOREIGN KEY(user_id) REFERENCES users "
        " (id) ON DELETE CASCADE "
        ") "
    )
    op.execute("CREATE INDEX ix_oauth_identities_user_id ON oauth_identities (user_id)")
    op.execute(
        "CREATE TABLE sessions ( "
        "        family_id UUID NOT NULL,  "
        "        user_id UUID NOT NULL,  "
        "        token_hash BYTEA NOT NULL,  "
        "        parent_id UUID,  "
        "        rotated_at TIMESTAMP WITH TIME ZONE,  "
        "        revoked_at TIMESTAMP WITH TIME ZONE,  "
        "        revoke_reason TEXT,  "
        "        idle_expires_at TIMESTAMP WITH TIME ZONE NOT NULL,  "
        "        absolute_expires_at TIMESTAMP WITH TIME ZONE NOT NULL,  "
        "        ip INET,  "
        "        user_agent TEXT,  "
        "        device_label TEXT,  "
        "        last_used_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,  "
        "        id UUID NOT NULL,  "
        "        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,  "
        "        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,  "
        "        CONSTRAINT pk_sessions PRIMARY KEY (id),  "
        "        CONSTRAINT ck_sessions_token_hash_length CHECK (octet_length(token_hash) = 32),  "
        "        CONSTRAINT ck_sessions_expiry_order CHECK (idle_expires_at <=  "
        "absolute_expires_at),  "
        "        CONSTRAINT ck_sessions_revoke_reason CHECK (revoke_reason IS NULL OR revoke_reason "
        " IN ('logout', 'logout_all', 'reuse_detected', 'password_changed', 'admin',  "
        "'user_suspended')),  "
        "        CONSTRAINT ck_sessions_revocation_consistent CHECK ((revoked_at IS NULL) =  "
        "(revoke_reason IS NULL)),  "
        "        CONSTRAINT ck_sessions_user_agent_length CHECK (user_agent IS NULL OR  "
        "char_length(user_agent) <= 512),  "
        "        CONSTRAINT fk_sessions_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON "
        " DELETE CASCADE,  "
        "        CONSTRAINT uq_sessions_token_hash UNIQUE (token_hash),  "
        "        CONSTRAINT fk_sessions_parent_id_sessions FOREIGN KEY(parent_id) REFERENCES  "
        "sessions (id) ON DELETE SET NULL "
        ") "
    )
    op.execute("CREATE INDEX ix_sessions_absolute_expires_at ON sessions (absolute_expires_at)")
    op.execute("CREATE INDEX ix_sessions_family_id ON sessions (family_id)")
    op.execute("CREATE INDEX ix_sessions_parent_id ON sessions (parent_id)")
    op.execute("CREATE INDEX ix_sessions_user_id ON sessions (user_id)")
    op.execute(
        "CREATE INDEX ix_sessions_user_id_created_at ON sessions (user_id, created_at) WHERE "
        "revoked_at IS NULL AND rotated_at IS NULL"
    )
    op.execute(
        "CREATE TABLE roles ( "
        "        key TEXT NOT NULL,  "
        "        name TEXT NOT NULL,  "
        "        description TEXT,  "
        "        is_system BOOLEAN DEFAULT false NOT NULL,  "
        "        id UUID NOT NULL,  "
        "        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,  "
        "        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,  "
        "        CONSTRAINT pk_roles PRIMARY KEY (id),  "
        "        CONSTRAINT ck_roles_key_format CHECK (key ~ '^[a-z][a-z_]{1,39}$'),  "
        "        CONSTRAINT uq_roles_key UNIQUE (key) "
        ") "
    )
    op.execute(
        "CREATE TABLE user_roles ( "
        "        user_id UUID NOT NULL,  "
        "        role_id UUID NOT NULL,  "
        "        granted_by UUID,  "
        "        granted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,  "
        "        CONSTRAINT pk_user_roles PRIMARY KEY (user_id, role_id),  "
        "        CONSTRAINT fk_user_roles_user_id_users FOREIGN KEY(user_id) REFERENCES users (id)  "
        "ON DELETE CASCADE,  "
        "        CONSTRAINT fk_user_roles_role_id_roles FOREIGN KEY(role_id) REFERENCES roles (id)  "
        "ON DELETE RESTRICT,  "
        "        CONSTRAINT fk_user_roles_granted_by_users FOREIGN KEY(granted_by) REFERENCES users "
        " (id) ON DELETE SET NULL "
        ") "
    )
    op.execute("CREATE INDEX ix_user_roles_granted_by ON user_roles (granted_by)")
    op.execute("CREATE INDEX ix_user_roles_role_id ON user_roles (role_id)")
    op.create_foreign_key(
        op.f("fk_audit_log_actor_user_id_users"), "audit_log", "users", ["actor_user_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        op.f("fk_idempotency_records_user_id_users"),
        "idempotency_records",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.execute(
        "INSERT INTO roles (id, key, name, is_system) "
        "VALUES ('0199e720-0000-7000-8000-000000000001', 'user', 'User', true)"
    )
    op.execute(
        "INSERT INTO roles (id, key, name, is_system) "
        "VALUES ('0199e720-0000-7000-8000-000000000002', 'admin', 'Admin', true)"
    )
    op.execute(
        "INSERT INTO roles (id, key, name, is_system) "
        "VALUES ('0199e720-0000-7000-8000-000000000003', 'super_admin', 'Super admin', true)"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_idempotency_records_user_id_users"), "idempotency_records", type_="foreignkey")
    op.drop_constraint(op.f("fk_audit_log_actor_user_id_users"), "audit_log", type_="foreignkey")
    op.drop_table("user_roles")
    op.drop_table("roles")
    op.drop_table("sessions")
    op.drop_table("oauth_identities")
    op.drop_table("credentials")
    op.drop_table("user_contacts")
    op.drop_table("users")
