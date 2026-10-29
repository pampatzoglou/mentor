# Architectural Styles — Catalog

Neutral by design. Each entry states the forces that favour it, the forces that kill it, how it
fails in practice, and what it costs to leave. No entry is the default.

## Read this first: three orthogonal axes

The word "architecture" collapses three independent decisions into one, and most circular design
arguments are two people picking different axes. Separate them:

| Axis | The decision | Range |
|---|---|---|
| **1. Decomposition** | How many independently deployable units | one process → module-enforced monolith → services → functions |
| **2. Integration** | How units exchange state | synchronous call → async command → event → shared store → CDC → batch |
| **3. Internal structure and state model** | How one unit is organised inside | layered → hexagonal; state-as-current-value → CQRS → event-sourced |

They are genuinely independent. A single-process monolith can be internally event-driven and
hexagonal. A fleet of services can be a layered CRUD system talking over HTTP. Choosing on axis 1
does not choose for you on axes 2 and 3, and pretending otherwise is where the "we did
microservices and it got worse" stories come from — the decomposition was copied and the
integration style was not reconsidered.

**Pick deliberately on each axis.** Then check the combination against the smells at the bottom.

---

# Axis 1 — Decomposition

## Single-process monolith

One deployable, one process, internal calls, usually one database. Structure enforced by
convention and review rather than by tooling.

- **Favoured by** — a small team; unknown or shifting domain boundaries; a latency budget that
  cannot afford hops; low operational capacity; strong transactional requirements across most of
  the domain; any early-stage system where the boundaries are still guesses.
- **Killed by** — genuinely divergent scaling curves; teams blocking each other on release; a
  compliance line cutting through the process; a codebase where nobody can predict what a change
  breaks.
- **Fails as** — the big ball of mud. Not because it is one deployable, but because nothing
  enforced the internal boundaries, so every module reaches into every other and change coupling
  becomes total. The failure is on axis 3, not axis 1.
- **Exit cost** — low to moderate *if* internal seams exist; very high if they do not. This is
  the entire argument for the modular monolith.
- **The tell that it is wrong** — release coordination meetings, or a change-failure rate that
  correlates with team size rather than change size.

## Modular monolith

One deployable, with module boundaries enforced mechanically — separate schemas or table
ownership, compile-time or lint-time import rules, module-owned public interfaces, no reaching
into another module's internals.

- **Favoured by** — a domain whose boundaries you believe you know but do not want to bet
  deployment topology on yet; a team count between one and a handful; the need for cross-module
  transactions today with the expectation of splitting some later; the same latency and
  operational arguments as the monolith, but with the extraction seam pre-built.
- **Killed by** — divergent scaling that a single process cannot satisfy; a hard isolation
  requirement; module boundaries that keep needing to move, which means they are wrong and the
  enforcement is now friction against learning.
- **Fails as** — enforcement decay. The import rule gets an exception, then ten, and it becomes a
  monolith with extra ceremony. The countermeasure is that the rule is mechanical and in CI, not
  social.
- **Exit cost** — low by construction. Extracting a module is a deployment and data-migration
  exercise rather than a redesign, which is the whole point.
- **The tell that it is wrong** — either the exceptions list is growing (enforcement is losing),
  or nothing has ever needed extracting (you are paying for optionality you do not use).

## Services

Multiple independently deployable units, each owning its data, communicating over a network.
Independent deployability is the defining property; if two units must ship together, they are one
unit with extra steps.

- **Favoured by** — divergent scaling curves; several teams needing independent release cadence;
  failure isolation that must be real; heterogeneous technology needs; compliance or trust lines
  requiring separation; a domain whose boundaries are known and stable.
- **Killed by** — invariants requiring immediate consistency across the proposed boundary; a
  latency budget that cannot absorb the hops; fewer teams than services; absent operational
  capacity — no distributed tracing, no per-service ownership, no on-call.
- **Fails as** — the distributed monolith: synchronous call chains, shared databases,
  release trains. Every cost of the network, none of the independence. Also fails as the
  *nanoservice* — units so small that behaviour lives in whatever orchestrates them.
- **Exit cost** — high in both directions. Merging services back is unusual and painful; splitting
  further compounds the coordination cost. Treat the first split as a one-way door until proven
  otherwise.
- **The tell that it is wrong** — a single user action fans out across four or more synchronous
  hops, or a deploy of one service requires deploying another.

## Functions

Per-request or per-event units, managed runtime, scale-to-zero, no long-lived process.

- **Favoured by** — spiky or very low traffic where scale-to-zero is a real saving; genuinely
  event-triggered work with no session state; glue and adapters at a system edge; operational
  capacity you would rather not build.
- **Killed by** — cold-start sensitivity in the latency budget; long-running or stateful work;
  high steady traffic, where the cost curve turns against you; heavy local dependencies; a need
  for the same runtime and tooling as the rest of the estate.
- **Fails as** — a distributed system nobody drew. Dozens of functions wired by queues and
  triggers, where the control flow exists only in cloud configuration and no one can answer what
  happens when the third one fails.
- **Exit cost** — moderate. The code often ports; the invocation model, local development story,
  and observability do not.
- **The tell that it is wrong** — you are reimplementing orchestration, retries, and state
  machines in glue configuration.

---

# Axis 2 — Integration

## Synchronous request/response

The caller waits. HTTP, gRPC, or an in-process call.

- **Favoured by** — the caller genuinely needs the answer to proceed; read-heavy queries; simple
  causality and debuggable stack traces; strong consistency reads from the owner.
- **Killed by** — availability coupling (the caller is now only as available as the callee, and
  the product of a chain drops fast); latency accumulation across hops; the callee needing to
  scale with the caller's traffic rather than its own.
- **Fails as** — the synchronous chain. A to B to C to D, where D's slowness becomes A's timeout
  and a retry storm becomes an outage. Circuit breakers and bulkheads are mitigations, not fixes.
- **The tell that it is wrong** — the caller does not use the response for anything except
  confirming the call happened. That is a command, not a query.

## Asynchronous command

The caller enqueues work addressed to one specific consumer, and does not wait. A queue, one
logical consumer, an instruction with an intended effect.

- **Favoured by** — work that need not complete within the request; load levelling and
  backpressure absorption; retry and dead-lettering as first-class behaviour; a producer that must
  stay available when the consumer is down.
- **Killed by** — the caller needing the result synchronously; ordering requirements the transport
  cannot guarantee; work whose failure must be surfaced to a waiting user.
- **Fails as** — invisible failure. Work is accepted, then dies in a retry loop nobody watches.
  A queue without dead-letter monitoring is a place where requests go to disappear.
- **Note** — a command names its consumer, an event does not. Broadcasting a command to whoever is
  listening produces a system where adding a subscriber changes existing behaviour.
- **Transport is a separate decision.** A queue deletes on acknowledgement; a log retains and lets
  consumers track offsets. Only the log supports replay and adding a consumer that must see
  history — and retrofitting one later means the history you needed was already deleted. See the
  comparison in `data-intensive.md`.

## Event notification

A thin fact published about the past — an identifier and a type, no payload of consequence.
Subscribers call back for detail if they need it.

- **Favoured by** — decoupling the producer from an unknown and growing set of consumers; adding
  consumers without touching the producer; low coupling to the producer's internal model.
- **Killed by** — consumers that all immediately call back for the same data, which reintroduces
  the synchronous dependency you were removing, now with extra latency; a consumer needing the
  state as it was at event time rather than as it is now.
- **Fails as** — the notification storm: N consumers each firing a query per event, turning one
  write into N reads against the producer.
- **The tell that it is wrong** — every subscriber's first action is a callback for the same
  fields. Those fields belong in the event.

## Event-carried state transfer

A fat event carrying the state a consumer needs, so the consumer keeps a local replica and never
calls back.

- **Favoured by** — consumers that must serve reads while the producer is unavailable; read
  amplification you want to remove from the producer; consumers needing point-in-time state.
- **Killed by** — a strict read-after-write requirement on the consumer side; payloads large
  enough that the transport becomes the bottleneck; a consumer set so diverse that the event grows
  to satisfy all of them and becomes a coupling surface of its own.
- **Fails as** — schema coupling by another name. The event now exposes the producer's model, and
  every consumer breaks when it changes. Version the event contract deliberately — see the
  contract rules in `boundaries.md`.
- **Cost you must state out loud** — the consumer's copy is stale by design, and "how stale" is
  the wrong question. It inherits read-your-writes, monotonic reads, and consistent prefix reads
  as three separate exposures; a consumer serving a UI needs the first two and will not get them
  from an event stream alone. Name the ones it tolerates per `data-intensive.md`.

## Shared database

Two or more units read and write the same tables.

Named here because it is the most common integration style in practice, not because it is
recommended. It is honest to call it a style and evaluate it.

- **Occasionally justified by** — a genuine transactional invariant across both units that nothing
  else can satisfy; a deliberate transitional state during an extraction, with an end date; a
  reporting reader with read-only access and an accepted coupling to the schema.
- **Killed by** — almost everything else. Two writers means neither owns the data, so neither can
  change the schema, and the boundary on the deployment diagram is fiction.
- **Fails as** — the coupling that cannot be seen. Nothing in either codebase declares the
  dependency; it is discovered during a migration, in production.
- **If you must** — make it one writer and N readers, give readers their own credentials and
  read-only role, and treat the schema as a published contract with the same versioning discipline
  as an API. Then write down when it ends.

## Log-based change data capture

Read the database's replication log and publish changes downstream.

- **Favoured by** — integrating with a system you cannot modify; needing every change with no
  application cooperation; analytical replication and warehousing.
- **Killed by** — needing business events rather than row mutations. CDC gives you *what changed
  in the schema*, not *what happened in the domain*, and the two diverge the moment the schema
  is refactored.
- **Fails as** — schema coupling at maximum reach. Every downstream consumer now depends on the
  source's physical table layout.
- **Boundary note** — mechanics, connector config, and topic layout belong to `/data`. Whether the
  boundary is crossed by CDC at all is the architectural question here.

## Batch transfer

Periodic bulk movement — a file, an export, a scheduled job.

- **Favoured by** — a latency requirement measured in hours; very large volumes where per-record
  overhead dominates; integration with systems that only speak files; a simple, restartable,
  auditable transfer.
- **Killed by** — a freshness requirement the window cannot meet; the volume growing until the
  job no longer fits in its window.
- **Fails as** — the silent window overrun. The job starts taking longer than its interval,
  overlaps itself, and corrupts or duplicates. Also fails as the all-or-nothing batch, where one
  bad record fails a million good ones.
- **Underrated** — for a real freshness budget of hours, batch is simpler, cheaper, and easier to
  reason about than streaming. Do not let it lose on fashion.

## Saga

A business transaction spanning multiple owners, implemented as a sequence of local transactions
with compensating actions. The answer to "we need a distributed transaction" when two-phase
commit is off the table.

- **Orchestrated** — a coordinator drives each step. Control flow is explicit and debuggable in
  one place; the coordinator becomes a dependency and can accrete domain logic.
- **Choreographed** — each participant reacts to the previous one's event. No central dependency;
  the overall flow exists nowhere and is inferred by reading every participant.
- **Favoured by** — a multi-owner process where each step can be compensated and eventual
  consistency is acceptable to the business.
- **Killed by** — steps that cannot be compensated (an irreversible external effect, a sent
  message, a shipped item) with no business-level remedy; an invariant that must never be
  observably violated, even briefly.
- **Fails as** — compensation that was never tested, or partial completion that leaves the system
  in a state no code models. The compensating paths need the same test rigour as the happy path,
  and usually get a fraction of it.
- **Before choosing it** — check whether the boundary is wrong. A saga is sometimes the cost of a
  split that should not have happened, and merging the two owners removes the need entirely.

## Outbox

Write the state change and the outgoing message in one local transaction, then relay the message
separately. The standard fix for the dual-write problem.

- **Solves** — the failure where a unit commits its state change and then crashes before
  publishing, or publishes and then fails to commit. Either way the system is inconsistent and
  nothing retries correctly.
- **Cost** — at-least-once delivery, so every consumer must be idempotent. That is a real
  requirement on every consumer, not a footnote. And transport-level deduplication does not
  satisfy it: a client retry produces a genuinely new message, so the idempotency key has to
  originate where the intent is formed and travel unchanged through every hop — the end-to-end
  argument in `data-intensive.md`.
- **Use it whenever** — a state change and a published message must both happen. If a design has a
  database write next to a publish call with no outbox and no idempotent consumer, that is a
  correctness bug, not a style preference.

---

# Axis 3 — Internal structure and state model

## Layered

Horizontal layers — presentation, application, domain, persistence — with calls going one way.

- **Favoured by** — familiarity and low ceremony; CRUD-shaped domains where the layers match the
  real structure of the work; small units.
- **Killed by** — rich domain rules that end up in the persistence layer because that is where the
  data is; a need to swap infrastructure without touching the domain.
- **Fails as** — the anaemic domain: entities are data holders, all behaviour sits in a service
  layer, and the domain rules are scattered across whatever touched them last.

## Hexagonal (ports and adapters)

The domain sits in the middle and declares interfaces. Infrastructure implements them from the
outside. Dependencies point inward, always.

- **Favoured by** — domain logic worth protecting from infrastructure churn; testability without
  standing up the world; more than one adapter for the same port (HTTP and queue, Postgres and
  in-memory); an intended infrastructure swap.
- **Killed by** — a unit that is genuinely a thin adapter itself, where the ceremony exceeds the
  domain; a team that will not maintain the discipline, leaving an abstraction layer that is
  bypassed half the time.
- **Fails as** — ports with exactly one adapter, forever, and an interface that mirrors that
  adapter's shape one-to-one. The abstraction costs indirection and buys nothing.
- **Note** — this is the axis-3 answer to most "our monolith is a mess" complaints. The problem is
  usually internal structure, and splitting deployables does not fix it — it distributes it.

## CQRS

Separate the write model from the read model. At minimum, different types on each path; at
maximum, separate stores kept in sync asynchronously.

- **Favoured by** — a read/write ratio and shape mismatch severe enough that one model serves
  neither well; reads needing denormalised or differently-indexed projections; independent scaling
  of the read side.
- **Killed by** — a read model that is essentially the write model, where you have doubled the
  code to serve the same shape; a hard read-after-write requirement, if the projection is
  asynchronous.
- **Fails as** — projection lag nobody budgeted for, surfacing as "I saved it and it is not
  there". That is the read-your-writes anomaly, and it has known mitigations rather than being an
  inherent cost — `data-intensive.md`. Also fails as premature separation, where two models must now be changed in lockstep for
  every field added.
- **Grades, from cheap to expensive** — separate types on one store; separate read replicas;
  separate projected store. Take the cheapest grade the forces justify, and note that the first
  grade is almost free and often sufficient.

## Event sourcing

State is the fold of an append-only event log. Current state is derived, never stored as the
source of truth.

- **Favoured by** — a domain where history *is* the requirement — audit, finance, compliance,
  temporal queries, "why is this value what it is"; a need to derive new projections
  retrospectively from facts you already captured.
- **Killed by** — a domain where only current state matters; a team without the operational
  appetite for versioning events forever, snapshotting, and replay; an expectation of querying
  current state ad hoc, which the log cannot serve without projections.
- **Fails as** — the immutable mistake. Events are permanent, including the ones with the wrong
  schema or bad data, so you inherit upcasting and versioning as a permanent tax. Also fails when
  events are modelled as CRUD rows renamed, so the log records `updated` rather than a domain
  fact and none of the auditability benefit materialises.
- **Cost you must state out loud** — event schema versioning is forever, and replay time grows
  with history unless snapshots are designed in from the start.
- **Pairing** — usually implies CQRS, since the log cannot serve arbitrary reads. Costing one
  without the other understates the commitment.
- **Ownership** — the log is the system of record and every projection is derived, which is what
  makes projections safe to rebuild. That property only holds while the full history is retained:
  truncate it and the projections quietly become authoritative with no backup story. See
  `data-intensive.md`.

---

# Combination smells

The axes are independent, but some combinations are self-defeating. These are worth checking
before the tradeoff table is written.

| Combination | Why it defeats itself |
|---|---|
| Services + shared database | Neither unit owns its data, so neither can change its schema. The distributed monolith in its purest form: all the network cost, none of the independence. |
| Services + synchronous chains three or more deep | Availability multiplies downward and latency accumulates. The split bought coupling at a higher price than the monolith charged. |
| Services + release train | If they ship together they are one unit. You are paying network and operational costs for a deployment boundary you do not use. |
| Event sourcing without CQRS | The log cannot serve arbitrary reads, so something will bolt on a query path anyway. Cost it up front. |
| CQRS with an asynchronous projection + read-after-write requirement | Structurally impossible to satisfy. Either the projection is synchronous or the requirement changes. |
| Event notification where every subscriber immediately calls back | The decoupling is nominal; the producer now serves N reads per write instead of zero. Move the fields into the event or accept the synchronous call. |
| Functions + a multi-step business process | The state machine ends up in cloud configuration, unversioned and untestable. Use an explicit orchestrator. |
| Modular monolith with an exceptions list to its own import rules | Enforcement has been lost. It is a monolith paying ceremony, and the extraction seam it was justified by does not exist. |
| Microservices with fewer teams than services | Every team context-switches across several deployables. The coordination cost is real and the independence benefit is not. |
| Two channels between the same pair of components | A store write plus a queued message race, and the consumer reads before the write is visible. Collapse to one channel or make the consumer tolerate it. |
| "Exactly once" claimed anywhere | Not available over an unreliable network. What is available is at-least-once with idempotent consumers; if the design has no idempotency key, the guarantee is imaginary. |
