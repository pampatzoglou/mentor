# Data-Intensive Reasoning

The criteria that decide a boundary once data crosses it. Distilled from *Designing
Data-Intensive Applications* (Kleppmann) and reframed as design tests rather than as a summary —
the value here is the questions, not the taxonomy.

Scope: this file reasons about **guarantees at a boundary**. Engine internals (isolation level
configuration, index choice, storage tuning) belong to `/dba`; pipeline mechanics (partition keys,
connector config, backfill) belong to `/data`. What a boundary *promises*, and whether that
promise is buyable at all, belongs here.

---

## The master heuristic: integrity over timeliness

Two things get called "consistency", and conflating them is the most expensive vocabulary error
in distributed design.

| | **Timeliness** | **Integrity** |
|---|---|---|
| Violated means | A reader saw stale data | Data is lost, duplicated, or contradictory |
| Duration | Temporary — it self-heals | Permanent — it does not heal on its own |
| Detected by | A user noticing something old | An audit, a reconciliation, or a customer complaint years later |
| Acceptable? | Frequently, if bounded and stated | Effectively never |

**The rule: relax timeliness freely, never relax integrity.** Eventual consistency is a
legitimate engineering trade. Perpetual inconsistency is a defect that happens to have been
shipped.

This reframes most "do we need strong consistency here?" arguments. Usually the answer is *no* for
timeliness and *yes, absolutely* for integrity, and the two get bundled into one question that
then gets answered wrongly in one direction or the other.

## System of record versus derived data

At every boundary, label each dataset one of two things:

- **System of record** — authoritative. Written once, the source of truth. Losing it is
  unrecoverable.
- **Derived** — computable from a system of record. Caches, search indexes, materialised views,
  read projections, denormalised copies, replicas, analytical tables.

**The defining property of derived data is that you can throw it away and rebuild it.** That is
what makes a CQRS projection safe, a search index disposable, and a cache a performance decision
rather than a correctness one.

Two failures follow directly:

- **Derived data that cannot be rebuilt is not derived.** It is a second system of record with no
  owner and no backup story. If the projection can only be reconstructed by replaying events you
  no longer retain, you have quietly promoted a cache to authoritative.
- **Two systems of record for the same fact** is the shared-database failure in another costume.
  One of them is derived; decide which, and make the derivation explicit and automatic.

Ask it directly: *if this store were deleted, could we rebuild it, from what, and how long would
it take?* An answer of "we would lose data" means it is a system of record and must be treated
like one.

## Describing load and latency honestly

Most scalability arguments fail because the load was never described. "It needs to scale" is not a
force; a load parameter is.

- **Name the load parameters first** — requests per second, read/write ratio, concurrent users,
  cache hit rate, rows per query, fan-out per request. Which one dominates is the architecture
  question; the rest are noise.
- **Use percentiles, never averages.** An average hides the tail entirely. Report p50, p95, p99,
  and p999. The slowest requests are frequently the most valuable customers, because they are the
  ones with the most data.
- **Tail latency amplifies with fan-out.** If one user action makes 10 parallel backend calls and
  each has a p99 of 100 ms, the action is slower than 100 ms unless *all ten* stay under p99 —
  roughly a 10% chance of hitting the tail per action. A single slow component sets the user's
  experience for a large minority of requests.

That arithmetic is the quantitative form of the chattiness test in `boundaries.md`. A boundary that
multiplies fan-out multiplies tail exposure, and the multiplication is worse than intuition
suggests.

## Replication lag is three different problems

"The replica is a bit behind" describes three distinct anomalies with three distinct fixes. State
which ones the boundary tolerates — not a single staleness number.

| Anomaly | What the user sees | Mitigation |
|---|---|---|
| **Read-your-writes** | They save something, immediately reload, and their own change is missing | Route reads that may reflect the user's own recent writes to the leader, or require the replica to be at least as fresh as the user's last write |
| **Monotonic reads** | Time appears to go backwards — data present on one page load is gone on the next | Pin a user to one replica, so lag is stable rather than varying per request |
| **Consistent prefix reads** | Causality inverts — an answer appears before its question, a reply before the message | Keep causally-related writes in one partition, or track causality explicitly |

The practical consequence for design: **"eventual consistency is fine here" is not an answer.**
The answer is which of these three a consumer can survive. Read-your-writes is usually the one
that matters, is usually the one nobody asked about, and is the one that produces bug reports
phrased as "it did not save".

Event-carried state transfer (see `styles.md`) inherits all three by construction. If a consumer
serves a UI, it almost certainly needs read-your-writes and monotonic reads, and it will not get
them from an event stream alone.

## Invariants across a boundary have no isolation level

Inside one database, concurrency anomalies are buyable — raise the isolation level and pay in
throughput. Two are worth knowing architecturally, because they are the ones that survive
"we use transactions":

- **Lost update** — two readers modify the same value concurrently and one overwrites the other's
  change. Fixed with atomic operations, explicit locking, or compare-and-set.
- **Write skew and phantoms** — two transactions each read a set, each individually preserves an
  invariant, and the combination breaks it. The classic shape: two on-call staff each check that
  someone else is on call, both see the other, and both go off call. Nothing either transaction
  did was wrong in isolation. Requires serializable isolation, or materialising the conflict so
  there is a row to lock.

**Now the architectural point.** Across a component boundary, *there is no isolation level to
raise*. Two owners cannot be serialised with respect to one another without a distributed
transaction protocol. So an invariant spanning a boundary has exactly three honest options:

1. **Move the invariant inside one owner** — the boundary was in the wrong place. Usually the
   correct and cheapest answer.
2. **Accept that it can be violated, and detect it** — reconcile asynchronously, alert on
   divergence, compensate. Requires the business to accept a transient violation *and* someone to
   own the reconciliation.
3. **Buy coordination** — a saga with tested compensation, or genuine consensus. Expensive, and
   the compensation paths need the same test rigour as the happy path.

There is no fourth option where the invariant simply holds because everyone is careful. If a
design implies one, that is the finding.

## Consistency claims not to overstate

- **Linearizability is expensive and rarely required.** It means the system behaves as if there
  were one copy of the data with atomic operations. It costs coordination, therefore latency, and
  it reduces availability. Where it genuinely is needed: leader election, uniqueness constraints,
  and cross-channel timing dependencies. Everywhere else it is a nice-to-have being charged as a
  requirement.
- **Cross-channel dependencies are a real design bug, not a rare edge case.** Two communication
  paths between the same pair of components race: a producer writes a file to object storage
  *and* publishes a message, and the consumer receives the message before the write is visible.
  If a boundary has two channels, either collapse them to one or make the consumer tolerate
  arrival before availability.
- **State CAP carefully or not at all.** It concerns one narrow model — linearizable, with total
  availability during a network partition — and says nothing about latency, nothing about other
  consistency models, and nothing about the many faults that are not partitions. "Pick two of
  three" is a slogan that has ended more design discussions than it has improved. The useful
  version: consistency trades against latency *continuously*, not only when the network breaks.
- **Causality is cheaper than total order.** Many requirements that sound like "we need global
  ordering" are really "we need cause to precede effect", which is satisfiable without consensus.
  Check which one you actually have before buying the expensive one.

## Compatibility is two directions, both required at once

Precise definitions, because the loose use of "backwards compatible" hides half the problem:

- **Backward compatible** — new code can read data written by old code. Usually straightforward;
  you know what the old format was.
- **Forward compatible** — old code can read data written by new code. Harder, and it is what
  requires the tolerant reader: old code must ignore fields it does not recognise rather than
  reject or drop them.

During any rolling upgrade both old and new code are running simultaneously, so you need both
directions at the same time. And the demands differ by how the data flows:

| Dataflow | The hard part |
|---|---|
| **Through a database** | Data outlives code. A field added by new code, then read and rewritten by old code, is silently dropped — data loss with no error. |
| **Through service calls** | Clients and servers upgrade independently and in either order. New servers must read old requests; old clients must survive new responses. |
| **Through async messages** | Sender and receiver are decoupled in *time*. A message may be consumed much later, by several consumers on different versions. With an event log, old messages are permanent. |

Schema evolution for events is therefore a first-day decision, not a first-break decision. See
the contract rules in `boundaries.md` for the mechanics.

## Log versus queue is an architectural choice

Both are "async messaging" and they are not interchangeable.

| | **Queue** | **Log** |
|---|---|---|
| Message after consumption | Deleted on acknowledgement | Retained; consumers track offsets |
| Ordering | Generally none across consumers | Total within a partition |
| Multiple independent consumers | Each message goes to one | Each consumer group sees everything |
| Replay, and new consumers over history | Not possible | The defining capability |
| Slow consumer | Backs up, may drop | Lags, catches up |
| Natural fit | Work distribution, per-message parallelism | Event distribution, derived data, projections |

**The decision rule:** if you will ever need to add a consumer that must see historical events, or
to rebuild derived data from source, you need a log — and retrofitting one later means the history
you needed was already deleted. If you need per-message parallelism and ordering is irrelevant, a
queue is simpler and cheaper. Deciding this by which system is already installed is how the
capability gets lost.

## Exactly-once does not exist at the transport; idempotence does

Two components cannot agree on delivery with certainty over an unreliable network. What is
achievable is *at-least-once delivery with idempotent consumers*, or effectively-once within a
single system that can transactionally couple processing with offset commits.

The end-to-end argument matters here: **deduplication at the transport does not make an operation
idempotent.** If the transport dedupes but the user's browser retries, or a client-side retry
generates a fresh request, the duplicate arrives as a genuinely new message. The idempotency key
has to originate at the point where the intent is formed — the client — and be carried unchanged
through every hop.

Practically, at every boundary that mutates state:

- A client-generated operation identifier travels with the request
- The receiver records processed identifiers and returns the prior result on a repeat
- The retention window for those identifiers is explicit and longer than the maximum retry window
- The operation is idempotent even if the identifier is lost — prefer set-to-value over
  increment-by, where the domain allows

## Assumptions the network will not honour

- **There is no shared clock.** Wall-clock timestamps from different nodes cannot order events;
  skew and time jumps are normal, not pathological. Use logical clocks or sequence numbers for
  ordering; use wall clocks for display and coarse timeouts only. "Last write wins" by timestamp
  is a data-loss strategy.
- **Any process can pause arbitrarily** — garbage collection, VM migration, page faults. A lease
  holder can be paused past expiry and resume believing it still holds the lease. The defence is a
  **fencing token**: a monotonically increasing number issued with the lease and checked by the
  resource, so a stale holder is rejected rather than trusted.
- **A timeout cannot distinguish slow from dead.** Every failure detection is a guess. Make the
  guess explicit, bound it, and design for being wrong in both directions.
- **Failure is partial.** A request can succeed while its response is lost, so the caller cannot
  know. This is why retries require idempotence rather than merely benefiting from it.

## Questions at every data-crossing boundary

Run these when a boundary carries data. An unanswered question here is a design gap, not a detail
for implementation to settle.

- [ ] Which side is the system of record for this data, and which side holds derived data?
- [ ] If the derived copy were deleted, could it be rebuilt — from what source, and in what time?
- [ ] Which replication anomalies can the consumer survive: read-your-writes, monotonic reads,
      consistent prefix? Not "is eventual consistency acceptable".
- [ ] Does any invariant span this boundary? If so: moved inside one owner, detected and
      reconciled, or coordinated — which, and who owns the reconciliation?
- [ ] Is the contract both backward and forward compatible, given that both versions run at once?
- [ ] Is delivery at-least-once? Then where is the idempotency key generated, and how long are
      identifiers retained?
- [ ] Are there two channels between these components that could race?
- [ ] Does anything order events by wall-clock time across nodes?
- [ ] What is the fan-out per user action, and what does that do to tail latency at p99?
- [ ] Is any claimed guarantee stronger than what was actually bought?
