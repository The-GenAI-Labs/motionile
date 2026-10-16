# 17. Keep authorization live and runtime content in modules

- Status: Accepted
- Date: 2026-10-16

## Context

Phase 6 makes roles, configuration and the public catalog editable while sessions and statically generated pages remain active. Token-only authorization would delay revocation until token expiry. Core cannot own mutable configuration tables under the module boundary rules. Catalog URLs also need a fixed hierarchy and permanent redirects after editorial changes.

## Decision

- Authorization resolves the user's current roles and effective permissions from a Redis cache backed by Postgres. Mutations invalidate affected entries after commit. The access token's roles claim is a display hint only. `super_admin` implicitly receives every registered permission, including permissions added later.
- `platform` owns system settings and feature flags. Other modules use its public interface. Settings are registry-defined, schema-validated, versioned and cache-invalidated.
- The catalog has exactly three public levels: category, subcategory and topic. Categories record their level, subcategories require a top-level parent, and topics attach only to subcategories. Every mutable catalog entity and feature flag carries an optimistic-concurrency version.
- Catalog slug changes append the former complete path to `catalog_slug_history`. Public resolution returns a permanent redirect from that path to the entity's current path.
- Topic search uses PostgreSQL `pg_trgm` similarity with GIN trigram indexes on title and summary.

## Consequences

Permission changes affect active sessions without waiting for access-token rotation. Database-backed runtime settings remain behind a module interface. Catalog services enforce depth rules that a self-referencing foreign key cannot express alone. Stored complete paths preserve redirects across later ancestor renames, and trigram search supports useful typo tolerance without another search service.
