from datetime import datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from motionile.core.config import get_settings
from motionile.core.db import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

EMBEDDING_DIMENSIONS = get_settings().ai.embedding_dimensions


class Skill(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "skills"
    __table_args__ = (
        CheckConstraint("visibility IN ('system', 'private')", name="visibility"),
        CheckConstraint("status IN ('draft', 'active', 'archived')", name="status"),
        CheckConstraint("(visibility = 'system') = (owner_user_id IS NULL)", name="ownership"),
        CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND char_length(slug) <= 64", name="slug_format"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 64", name="name_length"),
        CheckConstraint("char_length(description) BETWEEN 1 AND 1024", name="description_length"),
        Index(
            "ix_skills_owner_user_id_slug",
            "owner_user_id",
            "slug",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_skills_owner_user_id_created_at",
            "owner_user_id",
            "created_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_skills_owner_user_id", "owner_user_id"),
        Index("ix_skills_current_version_id", "current_version_id"),
    )

    owner_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    slug: Mapped[str]
    name: Mapped[str]
    description: Mapped[str]
    visibility: Mapped[str]
    status: Mapped[str] = mapped_column(server_default=text("'draft'"))
    current_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("skill_versions.id", ondelete="SET NULL", deferrable=True, initially="DEFERRED", use_alter=True)
    )
    is_enabled: Mapped[bool] = mapped_column(server_default=text("true"))


class SkillVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "skill_versions"
    __table_args__ = (
        UniqueConstraint("skill_id", "version", name="uq_skill_versions_skill_id_version"),
        CheckConstraint("scan_status IN ('pending', 'passed', 'flagged')", name="scan_status"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("octet_length(checksum) = 32", name="checksum_length"),
        CheckConstraint("jsonb_typeof(frontmatter) = 'object'", name="frontmatter_object"),
        CheckConstraint("char_length(body_md) <= 100000", name="body_md_length"),
        CheckConstraint("(scan_status = 'pending') = (scanned_at IS NULL)", name="scanned_consistent"),
        Index("ix_skill_versions_created_by", "created_by"),
        Index(
            "ix_skill_versions_scan_status_created_at",
            "scan_status",
            "created_at",
            postgresql_where=text("scan_status = 'pending'"),
        ),
    )

    skill_id: Mapped[UUID] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    body_md: Mapped[str]
    frontmatter: Mapped[dict[str, Any]] = mapped_column(JSONB)
    checksum: Mapped[bytes]
    scan_status: Mapped[str] = mapped_column(server_default=text("'pending'"))
    scan_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    scanned_at: Mapped[datetime | None]
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class SkillFile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "skill_files"
    __table_args__ = (
        UniqueConstraint("skill_version_id", "path", name="uq_skill_files_skill_version_id_path"),
        CheckConstraint(
            "path ~ '^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$' AND path NOT LIKE '%..%' AND char_length(path) <= 255",
            name="path_safe",
        ),
        CheckConstraint("size_bytes >= 0", name="size_bytes_non_negative"),
        CheckConstraint("octet_length(sha256) = 32", name="sha256_length"),
        Index("ix_skill_files_asset_id", "asset_id"),
    )

    skill_version_id: Mapped[UUID] = mapped_column(ForeignKey("skill_versions.id", ondelete="CASCADE"))
    path: Mapped[str]
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id", ondelete="NO ACTION"))
    content_type: Mapped[str]
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[bytes]


class SkillEmbedding(TimestampMixin, Base):
    __tablename__ = "skill_embeddings"
    __table_args__ = (
        Index(
            "ix_skill_embeddings_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    skill_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("skill_versions.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    model: Mapped[str]
