# Entity relationship diagrams

One diagram per domain. Columns shown are keys and the columns that define relationships; [`schema.md`](schema.md) has every column. Tables from another domain appear with only their key so the links are visible.

## Identity

```mermaid
erDiagram
    users ||--o{ user_contacts : "has"
    users ||--o| credentials : "has"
    users ||--o{ oauth_identities : "links"
    users ||--o{ sessions : "signs in with"
    sessions |o--o{ sessions : "rotates to"
    users ||--o{ user_roles : "is granted"
    roles ||--o{ user_roles : "is granted through"
    users |o--o{ user_roles : "grants"

    users {
        uuid id PK
        text status
        timestamptz deleted_at
    }
    user_contacts {
        uuid id PK
        uuid user_id FK
        text kind
        citext value
        timestamptz verified_at
        boolean is_primary
    }
    credentials {
        uuid user_id PK, FK
        text password_hash
    }
    oauth_identities {
        uuid id PK
        uuid user_id FK
        text provider
        text subject
    }
    sessions {
        uuid id PK
        uuid family_id
        uuid user_id FK
        uuid parent_id FK
        bytea token_hash
    }
    roles {
        uuid id PK
        text key
    }
    user_roles {
        uuid user_id PK, FK
        uuid role_id PK, FK
        uuid granted_by FK
    }
```

## Platform

```mermaid
erDiagram
    users |o--o{ audit_log : "acts in"
    users |o--o{ idempotency_records : "sends"
    roles ||--o{ role_permissions : "has"
    permissions ||--o{ role_permissions : "is granted by"
    users ||--o| user_preferences : "has"
    voices |o--o{ user_preferences : "is default in"
    users |o--o{ system_settings : "updates"
    users |o--o{ feature_flags : "updates"

    audit_log {
        uuid id PK
        uuid actor_user_id FK
        text actor_type
        text action
        text target_type
        text target_id
    }
    idempotency_records {
        uuid id PK
        text scope
        uuid user_id FK
        text key
        text status
    }
    permissions {
        uuid id PK
        text key
    }
    role_permissions {
        uuid role_id PK, FK
        uuid permission_id PK, FK
    }
    user_preferences {
        uuid user_id PK, FK
        uuid default_voice_id FK
    }
    system_settings {
        text key PK
        uuid updated_by FK
    }
    feature_flags {
        text key PK
        uuid updated_by FK
    }
    users {
        uuid id PK
    }
    roles {
        uuid id PK
    }
    voices {
        uuid id PK
    }
```

## Catalog and media

```mermaid
erDiagram
    categories |o--o{ categories : "parent of"
    categories ||--o{ topics : "contains"
    users |o--o{ assets : "owns"
    users |o--o{ voices : "clones"
    assets |o--o{ voices : "previews"
    voices ||--o| voice_consents : "is consented by"
    users ||--o{ voice_consents : "gives"
    assets ||--o{ voice_consents : "is sample for"
    jobs ||--o{ renditions : "renders as"
    assets |o--o{ renditions : "stores"
    jobs ||--o{ share_links : "is shared by"
    renditions ||--o{ share_links : "is served by"

    categories {
        uuid id PK
        uuid parent_id FK
        text level
        text slug
    }
    topics {
        uuid id PK
        uuid category_id FK
        text slug
    }
    catalog_slug_history {
        uuid id PK
        text entity_type
        uuid entity_id
        text old_path
    }
    assets {
        uuid id PK
        uuid owner_user_id FK
        text kind
        text storage_key
    }
    voices {
        uuid id PK
        uuid owner_user_id FK
        uuid preview_asset_id FK
        text provider
        text provider_voice_id
    }
    voice_consents {
        uuid id PK
        uuid voice_id FK
        uuid user_id FK
        uuid sample_asset_id FK
    }
    renditions {
        uuid id PK
        uuid job_id FK
        uuid asset_id FK
        text aspect
    }
    share_links {
        uuid id PK
        uuid job_id FK
        uuid rendition_id FK
        text slug
    }
    users {
        uuid id PK
    }
    jobs {
        uuid id PK
    }
```

## Generation

```mermaid
erDiagram
    users ||--o{ jobs : "requests"
    topics |o--o{ jobs : "seeds"
    jobs ||--o{ storyboards : "plans with"
    users |o--o{ storyboards : "approves"
    storyboards ||--o{ scenes : "contains"
    assets |o--o{ scenes : "voices"
    assets |o--o{ scenes : "animates"
    jobs ||--o{ job_events : "emits"
    jobs ||--o{ job_skills : "uses"
    skill_versions ||--o{ job_skills : "is used by"

    jobs {
        uuid id PK
        uuid user_id FK
        uuid topic_id FK
        text source
        text status
    }
    storyboards {
        uuid id PK
        uuid job_id FK
        integer version
        uuid approved_by FK
    }
    scenes {
        uuid id PK
        uuid storyboard_id FK
        integer position
        uuid audio_asset_id FK
        uuid html_asset_id FK
    }
    job_events {
        uuid id PK
        uuid job_id FK
        text type
    }
    job_skills {
        uuid job_id PK, FK
        uuid skill_version_id PK, FK
        text selection
    }
    users {
        uuid id PK
    }
    topics {
        uuid id PK
    }
    assets {
        uuid id PK
    }
    skill_versions {
        uuid id PK
    }
```

## AI configuration and skills

```mermaid
erDiagram
    prompt_templates ||--o{ prompt_versions : "versions"
    prompt_versions |o--o| prompt_templates : "is active in"
    users |o--o{ prompt_versions : "authors"
    users |o--o{ skills : "owns"
    skills ||--o{ skill_versions : "versions"
    skill_versions |o--o| skills : "is current in"
    users |o--o{ skill_versions : "authors"
    skill_versions ||--o{ skill_files : "packages"
    assets ||--o{ skill_files : "stores"
    skill_versions ||--o| skill_embeddings : "is embedded as"

    prompt_templates {
        uuid id PK
        text key
        uuid active_version_id FK
    }
    prompt_versions {
        uuid id PK
        uuid template_id FK
        integer version
        text eval_status
        uuid created_by FK
    }
    skills {
        uuid id PK
        uuid owner_user_id FK
        text slug
        uuid current_version_id FK
        timestamptz deleted_at
    }
    skill_versions {
        uuid id PK
        uuid skill_id FK
        integer version
        text scan_status
        uuid created_by FK
    }
    skill_files {
        uuid id PK
        uuid skill_version_id FK
        uuid asset_id FK
        text path
    }
    skill_embeddings {
        uuid skill_version_id PK, FK
        vector embedding
        text model
    }
    users {
        uuid id PK
    }
    assets {
        uuid id PK
    }
```

## Memory and RAG

```mermaid
erDiagram
    users ||--o{ memories : "remembers"
    users ||--o{ rag_sources : "adds"
    assets |o--o{ rag_sources : "stores"
    rag_sources ||--o{ rag_chunks : "is split into"
    users ||--o{ rag_chunks : "owns"

    memories {
        uuid id PK
        uuid user_id FK
        text kind
        vector embedding
        text model
    }
    rag_sources {
        uuid id PK
        uuid user_id FK
        uuid asset_id FK
        text kind
        text status
    }
    rag_chunks {
        uuid id PK
        uuid source_id FK
        uuid user_id FK
        integer position
        vector embedding
        text model
    }
    users {
        uuid id PK
    }
    assets {
        uuid id PK
    }
```

## Billing

```mermaid
erDiagram
    users ||--o| billing_customers : "is"
    products ||--o{ orders : "is bought in"
    products |o--o{ products : "supersedes"
    users ||--o{ orders : "places"
    subscriptions |o--o{ orders : "starts with"
    orders |o--o{ payments : "is paid by"
    subscriptions |o--o{ payments : "renews with"
    users ||--o{ payments : "makes"
    users ||--o{ subscriptions : "holds"
    products ||--o{ subscriptions : "plans"
    products |o--o{ subscriptions : "changes to"
    payments ||--o{ refunds : "is refunded by"
    users |o--o{ refunds : "initiates"

    products {
        uuid id PK
        text code
        text kind
        text plan_key
        bigint price_paise
        uuid supersedes_product_id FK
    }
    billing_customers {
        uuid user_id PK, FK
        text razorpay_customer_id
    }
    orders {
        uuid id PK
        uuid user_id FK
        uuid product_id FK
        uuid subscription_id FK
        text status
    }
    payments {
        uuid id PK
        uuid order_id FK
        uuid subscription_id FK
        uuid user_id FK
        text status
        bigint credits_granted
    }
    subscriptions {
        uuid id PK
        uuid user_id FK
        uuid product_id FK
        uuid pending_product_id FK
        text status
    }
    refunds {
        uuid id PK
        uuid payment_id FK
        uuid initiated_by FK
        text status
    }
    webhook_events {
        uuid id PK
        text provider
        text event_id
        text status
    }
    billing_reconciliation_runs {
        uuid id PK
        text type
        text status
        text report_storage_key
    }
    users {
        uuid id PK
    }
```

`webhook_events` and `billing_reconciliation_runs` have no foreign keys: events are stored before they are matched to any row, and a run describes a window rather than a row.

## Credits

```mermaid
erDiagram
    users ||--o| credit_wallets : "has"
    users ||--o{ credit_lots : "owns"
    users ||--o{ credit_reservations : "holds"
    users ||--o{ credit_ledger : "is credited in"
    users ||--o{ usage_records : "incurs"
    jobs |o--o{ usage_records : "costs"
    publications |o--o{ usage_records : "costs"

    credit_wallets {
        uuid user_id PK, FK
        bigint balance
        bigint reserved
    }
    credit_lots {
        uuid id PK
        uuid user_id FK
        text source
        bigint amount
        bigint remaining
        timestamptz expires_at
        text ref_type
        uuid ref_id
    }
    credit_reservations {
        uuid id PK
        uuid user_id FK
        bigint amount
        text status
        text ref_type
        uuid ref_id
    }
    credit_ledger {
        uuid id PK
        uuid user_id FK
        bigint delta
        bigint reserved_delta
        text idempotency_key
    }
    usage_records {
        uuid id PK
        uuid user_id FK
        uuid job_id FK
        uuid publication_id FK
    }
    users {
        uuid id PK
    }
    jobs {
        uuid id PK
    }
    publications {
        uuid id PK
    }
```

`credit_lots.ref_id` and `credit_ledger.ref_id` point at a payment, refund, reservation, lot or admin action by type, without a foreign key, so the ledger never blocks a purge of the thing it describes.

## Publishing

```mermaid
erDiagram
    users ||--o{ connected_accounts : "connects"
    platform_specs ||--o{ connected_accounts : "describes"
    connected_accounts ||--o| account_credentials : "authenticates with"
    users ||--o{ publications : "publishes"
    jobs ||--o{ publications : "is published in"
    publications ||--o{ publication_targets : "targets"
    connected_accounts ||--o{ publication_targets : "posts to"
    platform_specs ||--o{ publication_targets : "constrains"
    renditions ||--o{ publication_targets : "is uploaded as"

    platform_specs {
        text platform PK
    }
    connected_accounts {
        uuid id PK
        uuid user_id FK
        text platform FK
        text external_account_id
        text status
    }
    account_credentials {
        uuid connected_account_id PK, FK
        bytea ciphertext
        bytea nonce
        integer key_version
    }
    publications {
        uuid id PK
        uuid user_id FK
        uuid job_id FK
        text status
    }
    publication_targets {
        uuid id PK
        uuid publication_id FK
        uuid connected_account_id FK
        text platform FK
        uuid rendition_id FK
        text status
    }
    users {
        uuid id PK
    }
    jobs {
        uuid id PK
    }
    renditions {
        uuid id PK
    }
```

## Integrations

```mermaid
erDiagram
    users ||--o{ api_keys : "creates"
    users |o--o{ mcp_clients : "registers"
    users ||--o{ mcp_grants : "authorizes"
    mcp_clients ||--o{ mcp_grants : "receives"

    api_keys {
        uuid id PK
        uuid user_id FK
        text prefix
        bytea key_hash
    }
    mcp_clients {
        uuid id PK
        text client_id
        uuid created_by FK
    }
    mcp_grants {
        uuid id PK
        uuid user_id FK
        uuid client_id FK
        bytea refresh_token_hash
    }
    users {
        uuid id PK
    }
```
