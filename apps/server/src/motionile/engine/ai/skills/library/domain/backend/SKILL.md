---
name: backend
description: Explaining server-side application development - HTTP request lifecycle, REST and status codes, routing and middleware, authentication with sessions, cookies and tokens, SQL databases, indexes, transactions and ACID, ORMs and the N+1 problem, migrations, background jobs, idempotency, pagination and API design. Use for what happens inside one server application between a request arriving and a response leaving, not for multi-service scaling (system-design) or deployment (devops).
metadata:
  layer: domain
---

# Backend development

## When to use

Topics about code and data on the server: APIs, databases, auth, validation, errors, jobs. Audience: beginners learning how the web works, and working developers wanting a precise mental model. Pair with `system-design` only when the topic crosses to many services.

## Structure

1. Start from the request the viewer already knows (a button click, a page load) and follow it in.
2. Walk the layers in order: network and HTTP parse, middleware (logging, auth, rate limit), route handler, business logic, data access, response.
3. Introduce one concept per beat with a concrete payload or table, then say what goes wrong without it (no index, no transaction, no validation).
4. End on the failure case: what the client sees on error, and how the server stays consistent.

For a database topic, use the same two or three tables throughout (for example users and orders) so the viewer tracks one schema.

## Analogies and where they break

- Server as a restaurant kitchen taking tickets: handler is the cook, database the pantry. Breaks: a kitchen handles one order at a time, while a server handles many concurrently.
- Index as a book's index: jump to the page instead of reading everything. Breaks: every write must also update the index, so indexes slow writes and take space.
- Transaction as a bank transfer that either fully happens or does not. Breaks: isolation levels decide what concurrent transactions can see; "atomic" alone does not prevent every anomaly.
- Session as a coat-check ticket: the number is meaningless, the server holds the coat. Breaks: a signed token carries its own data, so there is nothing to look up.
- Middleware as security checkpoints in a corridor. Breaks: order matters and a skipped checkpoint is a bug.

## Misconceptions to preempt

- "REST means JSON over HTTP." REST is a set of constraints; resource-oriented URLs with HTTP methods are the common practical subset.
- 401 means the client is not authenticated; 403 means authenticated but not allowed (the names are historically confusing).
- JWTs are encrypted. A standard signed JWT is encoded and signed, not hidden; anyone can read its payload. Never put secrets in it.
- Hashing is encryption. Passwords are hashed with a slow, salted function built for it (argon2id, scrypt or bcrypt), never a plain fast hash.
- "Async means parallel." Async lets one thread wait on I/O without blocking; it does not add CPU parallelism.
- More indexes are always better.
- PUT and DELETE are idempotent by definition; POST is not, so retry-safe creation needs an idempotency key.
- ORMs remove the need for SQL; they hide it, which is how N+1 queries happen.

## Terminology

Say request, response, header, body, status code, endpoint, route, handler, middleware, payload, schema, validation, query, join, primary key, foreign key, transaction, rollback, isolation level, connection pool, migration, queue, worker, idempotent. Say "authentication" (who you are) and "authorization" (what you may do). Use "N+1 queries", not "slow queries". Avoid "the cloud" as a place and "API" without saying which side.

## Visual pairings

- flow-diagram: request lifecycle, auth handshake, retry with idempotency key.
- code-walkthrough: a short handler, a query, a middleware chain.
- timeline-sequence: two concurrent transactions, token expiry and refresh.
- data-structure-operations: B-tree index lookup, rows moving across a join.
- comparison-split: session versus token, offset versus cursor pagination, SQL versus document store.
- architecture-build-up: app, database, cache, worker added one at a time.

## Accuracy checks

- Status codes: 200 OK, 201 Created, 204 No Content, 400 Bad Request, 401, 403, 404, 409 Conflict, 422 Unprocessable Content, 429 Too Many Requests, 500, 503. Do not invent codes.
- Default isolation level differs by database; state the database before claiming what a transaction prevents.
- Index lookups in a B-tree are logarithmic in table size, not constant.
- Cursor pagination stays stable under inserts; offset pagination can skip or repeat rows and gets slower with large offsets.
- Money is stored in the smallest integer unit, never floating point.
- Name the language or framework only if the scene needs it; otherwise stay generic. State framework versions when behavior differs between them.

## Do

- Show the real data shape (a request body, a row) rather than the word "data".
- Show both the success path and one error response with its code.
- Explain why a rule exists by showing what breaks without it.

## Don't

- Don't show secrets, real keys or real user data; use obviously fake values.
- Don't recommend storing tokens or sessions in ways that skip the browser's protections without saying the trade-off.
- Don't say "always" about caching, indexes or normalization.
