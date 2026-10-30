# 38. Model provider traffic outside SafeHttpClient, and the uuid-utils override

- Status: Accepted
- Date: 2026-10-29
- Refines: [ADR 0011](0011-imdsv2-hop-limit-two.md)

## Context

AGENTS.md routes all outbound HTTP through `SafeHttpClient`. LiteLLM (model calls and embeddings) and the Langfuse SDK (traces) bring their own HTTP stacks, and rewriting them onto `SafeHttpClient` would mean forking both libraries. Separately, `langchain-core` 1.2 and later, which the LangGraph Postgres checkpointer needs, pins `uuid-utils<1.0`, while the repository generates every primary key with `uuid-utils` 1.x.

## Decision

- LiteLLM and Langfuse may make outbound requests themselves, under these conditions: the hosts are fixed provider endpoints (the Langfuse host must be an HTTPS origin validated by `AiSettings`), API keys are passed explicitly from `Settings` and never read from the environment by the libraries, the `litellm` import happens in one module (`engine/ai/llm/litellm_gateway.py`) that sets `LITELLM_LOCAL_MODEL_COST_MAP` before the import so the library does not download its cost map, and LiteLLM and Langfuse log at WARNING so request bodies never reach logs. Everything else still uses `SafeHttpClient`.
- Request content sent to a provider is limited to what the pipeline puts in a prompt: user text as delimited data, narration and skills. Tracing redacts contact details and tokens before data leaves the process.
- The same override list requires `filelock>=4.2.1`: `litellm` caps it below 4, while 3.x carries a high-severity advisory (arbitrary file overwrite). LiteLLM only uses `FileLock` for its local cache, which 4.x keeps. Remove the override when `litellm` allows 4.x.
- `apps/server/pyproject.toml` overrides `uuid-utils` to `>=1.0.0` for the whole dependency tree. `langchain-core` only needs `uuid7`, which 1.x keeps; a unit test builds a UUIDv7 through both `motionile.core.ids` and `langchain_core.utils.uuid`. The override is removed when `langchain-core` allows `uuid-utils` 1.x.

## Consequences

- Model providers see the prompts we send them; the egress allowlist on the instance must include the provider and Langfuse hosts.
- Upgrading `litellm`, `langfuse` or `langchain-core` needs the override and the cost-map behaviour re-checked.
