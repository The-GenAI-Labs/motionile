---
name: cs-fundamentals
description: Explains textbook computer science for students - algorithms (searching, sorting, recursion, graph traversal, dynamic programming, greedy), data structures (arrays, linked lists, stacks, queues, trees, heaps, hash tables, graphs), Big-O time and space complexity, binary and number systems, CPU and memory hierarchy, operating system concepts (processes, threads, scheduling, virtual memory, deadlock) and networking basics (IP, TCP, UDP, DNS, OSI layers). Use for CS courses, interview-style concepts and how a computer works at the bottom.
metadata:
  layer: domain
---

# CS fundamentals

## When to use

Queries about core computer science taught in school and the first university years: how an algorithm or data structure works and what it costs, how hardware and an operating system run programs, how data moves across a network. Production architecture, services, deployment and security belong to the tech domains; this skill supplies the underlying theory.

## Structure

1. Hook with a cost or a puzzle: finding a name among a billion, why one program freezes.
2. Give the idea in plain words and one concrete small instance (five numbers, three processes, two computers).
3. Step through the mechanism on that instance, one operation per beat, with the state visible after each step.
4. Name the cost: the count of steps as a function of input size n.
5. Contrast with the naive alternative on the same instance.
6. Generalise to the rule and state the conditions (sorted input, non-negative weights, reliable link).
7. Preempt the misconception, then one use.

Beginner: the idea with a tiny instance and no notation. Intermediate: pseudocode-level steps and Big-O. Advanced: invariants, worst versus average, trade-offs.

## Analogies and where they break

- Array as numbered lockers: instant access by number; breaks for insertion, where everything must shift.
- Linked list as a treasure hunt with clues: each node points to the next; breaks for random access.
- Stack as a plate pile, queue as a ticket line: exact LIFO and FIFO; break only for priority queues.
- Hash table as a library index by first letters: shows buckets; breaks because a good hash spreads keys evenly and collisions need handling.
- Process as a running program with its own house, thread as a roommate sharing the house: shared memory is the point; breaks for the cost of switching.
- Cache as a desk drawer versus the filing room: nearer is faster; breaks for coherence between several caches.
- Packet as a numbered postcard: shows splitting and reassembly; breaks because postcards are not retransmitted by the sender automatically.

## Misconceptions to preempt

- Big-O is an upper bound on growth in n, not a measured time; it ignores constants, so an O(n^2) method can beat O(n log n) on small inputs.
- Binary search needs sorted data; its cost is O(log n).
- A hash table lookup is O(1) on average, O(n) in the worst case.
- Best, average and worst case are different statements; say which one.
- Quicksort is O(n log n) on average and O(n^2) in the worst case; merge sort is O(n log n) always and needs O(n) extra space.
- Recursion is not inherently slow; it needs a base case and each call uses stack space.
- Concurrency (interleaving tasks) is not parallelism (running at the same time); more cores do not speed up sequential code.
- RAM is working memory and is lost without power; it is not storage. A deleted file is usually unlinked, not erased.
- The internet is the network of networks; the web is one service on it. Bandwidth (capacity) is not latency (delay).
- TCP gives reliable ordered delivery on top of an unreliable network; UDP does not. HTTPS encrypts content, but the server address is still visible to the network.
- A hash is not encryption: it is one-way and cannot be undone.

## Terminology and notation

- Name the quantity: "n elements", "V vertices and E edges". Write O(n log n), O(1), O(2^n) with the O upright.
- Zero-based indexing: the first element has index 0; state when pseudocode uses one-based indexing.
- Bits and bytes: 1 byte is 8 bits; KB means 1,000 bytes and KiB means 1,024; say which you mean. Hex digits group four bits.
- Say "stack" for the LIFO structure and "call stack" for function frames; "heap" is the priority-queue structure and, in memory, a separate region.
- Names: breadth-first search (queue), depth-first search (stack or recursion), Dijkstra's algorithm (non-negative edge weights), dynamic programming (overlapping subproblems), greedy (locally best choice, correct only when proven).
- Deadlock needs four conditions together: mutual exclusion, hold and wait, no preemption, circular wait.
- TCP three-way handshake: SYN, SYN-ACK, ACK. Layers: the TCP/IP model has four, the OSI model seven.

## Anchors worth stating

- 2^10 = 1,024, 2^20 is about a million, 2^30 about a billion; log2 of a billion is about 30, so binary search finds an item among a billion in about 30 steps.
- Sum of 1 to n is n(n + 1)/2; building a heap is O(n); inserting into a heap is O(log n).
- A 3 GHz clock is 3 billion cycles per second, about 0.33 ns per cycle.
- Rough latencies: L1 cache about 1 ns, main memory about 100 ns, SSD tens of microseconds, hard disk several milliseconds; present as orders of magnitude, not exact.
- IPv4 addresses are 32 bits (about 4.3 billion); IPv6 are 128 bits. A port is 16 bits (0 to 65,535). HTTP uses 80, HTTPS 443, DNS 53, SSH 22.

## Pair with visual skills

- `data-structure-operations`: insert, delete, search, traverse, rotate, heapify, graph traversal on a tiny instance.
- `code-walkthrough`: the algorithm as code, line by line, tied to the state shown beside it.
- `flow-diagram`: process states, fetch-decode-execute, handshakes, request paths, packet routes.
- `architecture-build-up`: memory hierarchy, OS layers, the network stack.
- `comparison-split`: process versus thread, TCP versus UDP, array versus linked list, BFS versus DFS.
- `data-chart-story`: growth curves of O(n), O(n log n), O(n^2), O(2^n), measured timings.
- `math-equation`: recurrences, binary and hex conversion, probability of collisions.

## Accuracy checks for the planner

- Run the algorithm on the chosen instance by hand; every intermediate state shown must be correct, including ties and duplicates.
- Use at most 8 to 10 elements on screen.
- State preconditions (sorted, connected, non-negative weights) before the result.
- Separate time and space complexity; separate average from worst case.
- Check conversions: the binary of 13 is 1101, the hex of 255 is FF.

## Don't

- Say "O(n) means exactly n steps" or compare algorithms by Big-O alone for tiny inputs.
- Use real network addresses of third parties; use documentation ranges (192.0.2.x) or private ones (192.168.x.x).
- Describe system design, cloud or security practice here; leave that to the tech domains.
- Show code in a language without naming it; prefer pseudocode when the idea is language-independent.
