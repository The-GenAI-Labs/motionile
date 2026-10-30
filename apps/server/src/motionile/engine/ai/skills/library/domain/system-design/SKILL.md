---
name: system-design
description: Explaining how large software systems are put together to scale and stay available - load balancers, caches, CDNs, message queues, database replication and sharding, consistent hashing, CAP and consistency trade-offs, rate limiting, back-of-envelope capacity estimates, and "how would you design X" walkthroughs such as a URL shortener, news feed or chat service. Use for architecture-level questions about many components working together, not for the code inside one service.
metadata:
  layer: domain
---

# System design

## When to use

Topics about components and the trade-offs between them: scaling reads or writes, surviving failures, latency versus consistency, "design a ...", "how does X handle millions of users". Audience is mostly beginners to intermediate engineers and interview preparers. If the topic is the internals of one service (routes, ORM, auth), the `backend` skill leads; for deployment pipelines, `devops`.

## Structure

1. Requirements first: what the system does, scale (users, requests per second, data size), and what matters most (latency, availability, consistency, cost). One scene.
2. Smallest working design: client, one server, one database. Name its first bottleneck.
3. Fix one bottleneck per scene, in the order they appear: stateless app servers behind a load balancer, then a cache for hot reads, then replicas for read load, then sharding for write load or data size, then a queue for slow or bursty work.
4. For each addition say what it costs: a new failure mode, stale data, operational complexity.
5. Close with the trade-off summary, not a "final perfect design".

A video on one topic should build one diagram that grows. Preserve component positions between scenes so the viewer recognizes the system.

## Analogies and where they break

- Load balancer as a restaurant host seating guests at open tables. Breaks: real balancers also health-check and remove broken servers, and a host sees every guest, while L4 balancers do not read the request.
- Cache as a notepad on your desk versus the filing cabinet. Breaks: a desk note can silently go stale; the hard part is invalidation.
- Sharding as splitting a phone book into volumes by last name. Breaks: a poor split key creates a hot volume, and queries across volumes need extra work.
- Replication as photocopies of a ledger. Breaks: copies lag the original, so a reader can see old data.
- Queue as a ticket line at a counter. Breaks: tickets can be delivered twice, so workers must tolerate repeats.

## Misconceptions to preempt

- "Add more servers and it scales." Only stateless tiers scale this way; the database usually becomes the limit.
- CAP is "pick two of three". Partitions happen on real networks, so during a partition a system chooses between consistency and availability. Without a partition it can have both. Say "during a network partition".
- Caching always helps. It adds staleness and a cold-start problem.
- Sharding and replication are the same. Replication copies the same data; sharding splits different data.
- "Exactly-once delivery" is easy. Practical systems use at-least-once delivery plus idempotent processing.
- Eventual consistency means "wrong". It means replicas converge if writes stop.

## Terminology

Say horizontal scaling (more machines) versus vertical scaling (bigger machine). Latency (time for one request) versus throughput (requests per unit time). Availability as a percentage; read-replica versus primary; partition key; consistent hashing (adding a node moves only a fraction of keys); TTL; cache hit ratio; back-pressure; idempotent. Say "stateless" for servers that keep no per-user data between requests. Avoid "infinitely scalable" and "real time" unless a number backs it.

## Visual pairings

- architecture-build-up: the core of every system-design video.
- flow-diagram: one request path, a cache hit versus miss, a write through a queue.
- comparison-split: SQL versus NoSQL choices, cache-aside versus write-through, replication modes.
- data-chart-story: latency or throughput before and after a change; availability budgets.
- timeline-sequence: failover steps, leader election, request over time between services.
- data-structure-operations: consistent-hashing ring, key moving between shards.

## Accuracy checks

- Seconds per day is 86,400, so 1 million requests per day is about 12 per second on average; peaks are often several times the average. State the peak factor you assume.
- Latency numbers are orders of magnitude only: memory access about 100 nanoseconds, a round trip inside one data center about half a millisecond, a cross-continent round trip about 100 milliseconds or more. Say "roughly".
- Availability: 99.9 percent allows about 8.8 hours of downtime a year, 99.99 percent about 53 minutes. Keep units consistent.
- Do not name a product as the only solution; say "a relational database", "a key-value store", "a message broker", and name products only as examples.
- Read-your-writes, monotonic reads and linearizability are different guarantees; do not call all of them "consistency".
- Every number you put on screen must follow from the stated assumptions.

## Do

- Show a failure on screen (a server dies, a replica lags) and what the design does about it.
- State the assumption behind every number.
- Give each component one sentence that says what problem it solves.
- Keep to five or six components per video for 60 seconds.

## Don't

- Don't present one design as the correct answer; say what would change it.
- Don't pile on microservices, Kubernetes or queues before a bottleneck justifies them.
- Don't claim how a named company's internal system works.
