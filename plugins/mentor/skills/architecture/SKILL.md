---
name: architecture
description: 'Choose and defend a system architecture — decomposition style, integration style, and where the boundaries go. Use when a design question is open: whether to split or merge services, sync or async between components, which component owns which data, how to evolve a monolith, how services exchange state, or when a decision needs recording as an ADR. Neutral on style: it supplies the forces, the selection procedure, and the tradeoff method, not a house default. Also covers the guarantees a boundary makes about data crossing it — integrity versus timeliness, system of record versus derived, replication anomalies, compatibility, idempotence. Triggers on architecture, system design, service boundaries, bounded context, coupling, decomposition, monolith vs microservices, event-driven, CQRS, event sourcing, saga, outbox, ADR, eventual consistency, replication lag, read-your-writes, linearizability, CAP, schema evolution, backward compatibility, exactly-once, idempotency, system of record.'
requires: [document]
---

# Architecture

## What this skill is, and what it refuses to be

This skill is **neutral about style and opinionated about method**. It will not tell you that a
modular monolith beats services, or that events beat request/response. Those answers depend on
forces this skill cannot see from here — your load asymmetry, your team count, your latency
budget, your operational capacity.

What it does supply, and holds firm on:

1. **The forces are stated before the style is named.** A style proposed before the forces are
   on the table is a preference wearing a costume.
2. **Every option carries its cost out loud.** An option presented without what it sacrifices
   has not been analysed, it has been advocated for.
3. **The decision names what would change it.** A decision nobody can falsify is a belief.

If you catch yourself reaching for a style because it is familiar, current, or already running
elsewhere in the estate, that is the moment to go back to step 1.

## Load first

- `document` — when the decision has been implemented and `docs/ARCHITECTURE.md` needs to
  describe the result. That skill owns the documentation suite and its Mermaid conventions
  (Mermaid first, SVG as fallback); this one owns the ADR that records *why*. Do not restate its
  diagram conventions here — use them.

## Routing

Four separable questions hide behind the word "architecture". Identify which one is actually
being asked, because the answers live in different places and mixing them is the most common way
a design conversation goes in circles.

| The question actually being asked | Go to | What it settles |
|---|---|---|
| "Monolith or services? Events or calls? Do we need CQRS?" | `styles.md` | The catalog, on three orthogonal axes, with the forces that favour and kill each |
| "Where does the line go? What does this component own?" | `boundaries.md` | Seven tests a boundary must pass, where to cut, where never to cut, and how to leave a seam |
| "We have chosen. How do we record and defend it?" | `decisions.md` | Tradeoff tables, reversibility classing, the ADR format, revisit triggers |
| "What does this boundary actually promise about the data crossing it?" | `data-intensive.md` | Integrity versus timeliness, system of record versus derived, the three replication anomalies, compatibility in both directions, idempotence |

Most real requests need at least two: a style question is not answered until the boundary it
implies passes the tests, and neither is finished until the consequences are written down.
**Any boundary that carries data also needs the fourth** — that is where the guarantees are either
bought or quietly assumed.

## Ownership boundaries — read before answering

This skill owns **structure and the reasoning about structure**: what the components are, what
each one owns, how they exchange state, and why. It stops at the point where another skill or
persona owns the concrete standard. When a task crosses one of these lines, say so and hand over
rather than inventing a second opinion.

| Surface | Who owns it | This skill's job |
|---|---|---|
| Engine internals — schema, indexing, query plans, pooling mode, storage layout | `/dba` persona | Own the *topology*: read/write split, replica-staleness tolerance, pooler placement, connection budget across components. Hand over the tuning values. |
| Pipeline mechanics — topic settings, partition keys, table engines, dedup and backfill implementation | `/data` persona | Own *whether* a boundary is crossed by event, query, or batch, and what the contract guarantees. Hand over the DDL and topic config. |
| Reliability targets and failure tooling — SLIs/SLOs, error budgets, alerting, timeout and retry values, probes | `/sre` persona | Own *failure independence*: which component may fail without taking another with it, and where the bulkhead goes. Hand over the numbers. |
| Threat model, trust boundaries, authn/authz design | `/security-architect` persona | Name where a boundary is also a trust boundary, then bring them in. Never settle a trust question alone. |
| Cloud substrate, DR topology driven by RPO/RTO, IAM | `/cloud` persona | State the durability and locality requirement; they choose the substrate that meets it. |
| Deployment topology — charts, values layering, sync waves, environments, cluster shape | `helm`, `kubernetes`, `argo-applicationset` skills | Stop at the deployable unit. How many deployables and what each owns is architecture; how they are packaged and rolled out is theirs. |
| Credential paths, mount conventions, the `*_FILE` contract | `secrets` skill | Note that a boundary needs a credential; never redesign the contract. |
| `docs/ARCHITECTURE.md`, README, diagram conventions | `document` skill | Write the ADR. Let `document` describe the implemented reality — it documents what exists, never intentions. |
| Sequencing, scope, and who does the work | `/staff` and `/pm` personas | Say what must be decided now versus deferred behind a seam. They own the plan. |

## The forces

An architecture is determined by forces, not preferences. Establish these before naming a style.
Where a number is unknown, **write "unknown" rather than guessing** — an unknown force is itself a
finding, and usually the strongest argument for deferring the decision behind a seam.

| Force | The question | Why it decides things |
|---|---|---|
| **Change coupling** | What changes together in the same week? | Things that change together belong together. This is the single strongest signal and it is measurable — see the co-change analysis in `boundaries.md`. |
| **Transactional scope** | Which invariants must hold atomically? | An invariant that must be immediately consistent cannot be split across a network without buying a distributed transaction protocol. Across a boundary there is no isolation level to raise — see `data-intensive.md`. A hard constraint, not a preference. |
| **Load asymmetry** | Which parts need to scale on different curves? | Uniform load is an argument against splitting for scale. A 100:1 read/write ratio or one hot path in ten is an argument for it. |
| **Latency budget** | What is the end-to-end budget, and how many hops fit in it? | Every network boundary spends budget and adds a failure mode. Count the hops per user action. |
| **Failure independence** | What must keep working when this fails? | If A failing must not take down B, they need a boundary *and* a fallback. If they may fail together, a boundary buys you complexity with no reliability return. |
| **Data gravity and ownership** | Who is the single writer of this data? | Two writers to one dataset is not a boundary, whatever the deployment diagram says. Label each dataset system of record or derived, and confirm the derived copy is genuinely rebuildable — `data-intensive.md`. |
| **Team topology** | How many teams, and can one own this end to end? | Conway's law is descriptive, not aspirational. More deployables than teams is a coordination tax; more teams than deployables is a contention tax. |
| **Operational capacity** | Can you actually run, observe, and debug N of these? | Distributed tracing, per-component SLOs, and on-call rotation are the entry fee. If the fee is unpaid, the split will be reverted. |
| **Compliance and trust** | Does a regulatory or trust line cut through here? | These lines are non-negotiable and often force a boundary the other forces would not justify. Loop in `/security-architect`. |
| **Reversibility** | If this is wrong in a year, what does it cost to undo? | Governs how much analysis the decision deserves. Classify it — see `decisions.md`. |

## Procedure

Work these in order. Skipping to step 3 is the failure mode this procedure exists to prevent.

### 1. Restate the problem and gather the forces

Restate what is being decided in one sentence, then fill in the forces table above. Mark unknowns
explicitly. If more than two or three forces are unknown, the honest output is a proposal for how
to find out — a spike, a load measurement, a co-change analysis — not an architecture.

### 2. Extract the hard constraints

Separate the invariants and compliance lines from everything else. These eliminate candidates
outright, and eliminating candidates is cheaper than comparing them. Typical hard constraints:

- An invariant requiring immediate consistency across two datasets
- A latency budget that cannot absorb another network hop
- A regulatory line requiring data residency or isolation
- An availability requirement one component genuinely cannot inherit from another

### 3. Name two or three candidates

Pick from `styles.md`, on each of the three axes it defines. Two candidates is usually enough;
more than three means the constraints in step 2 are underspecified. **Include the incumbent
option** — "keep what we have" is a legitimate candidate and frequently the winner, and it is the
baseline the others must beat.

### 4. Test each candidate's boundaries

For every candidate, run its proposed boundaries through the tests in `boundaries.md`. A style
that fails the data-ownership or transactional test is not a viable candidate — drop it here
rather than carrying it into the comparison and losing the argument later.

Where the boundary carries data, also work the questions at the end of `data-intensive.md`. They
surface the guarantees a design is silently assuming, and an assumed guarantee is the most
expensive kind.

### 5. Compare, recommend, record

Build the tradeoff table and write the ADR per `decisions.md`. The output has four parts, and the
last two are the ones usually missing:

1. The recommendation and why it wins on these forces
2. What it costs — the sacrificed axis, named
3. **The seam**: what stays swappable so a wrong call can be corrected
4. **The revisit trigger**: the observable condition under which this is reopened

## Anti-patterns

These are the failure modes worth naming out loud when you see them, including in your own draft.

- **Style before forces.** The style was chosen, then reasons were assembled. The tell is a
  tradeoff table where every row favours the same option.
- **Resume-driven design.** The technology is interesting rather than indicated. The tell is that
  the forces section is thin and the implementation section is thick.
- **The distributed monolith.** Separate deployables that must be released together, share a
  database, or call each other synchronously in a chain. You have paid for every cost of the
  split and received none of its benefits. This is the most common bad outcome of decomposition.
- **Boundaries by technical layer.** A "service" per layer — API service, business-logic service,
  data service. Every feature crosses every boundary, so nothing changes independently.
- **Entity services.** One CRUD service per database table. The boundaries follow the schema
  rather than the behaviour, and orchestration leaks into whatever calls them.
- **"We will extract it later"** with no seam. Extraction later is only real if the interface and
  the data ownership are already separate. Otherwise it is a plan to do the hard part later, with
  more code.
- **Consequences that are all upside.** If the consequences section of a decision lists no cost,
  the analysis is incomplete. Every architecture sacrifices something.
- **Overclaimed guarantees.** The design says "eventually consistent" while the product assumes
  read-your-writes, or says "exactly once" when the transport provides at-least-once. Nobody lied
  and the system is still wrong. `data-intensive.md` lists the claims worth checking.
- **Symmetry for its own sake.** Every component built to the same template regardless of its
  load, criticality, or rate of change. Uniformity is a real benefit, but it is a choice with a
  cost, not a default.

## Completion checklist

A design answer from this skill is finished when:

- [ ] The problem is restated in one sentence and the forces table is filled in, unknowns marked
- [ ] Hard constraints are separated from preferences, and each eliminated candidate says which constraint eliminated it
- [ ] Two or three candidates were compared, including the incumbent
- [ ] Each surviving candidate's boundaries passed the tests in `boundaries.md`, with the data owner named for every dataset
- [ ] For every data-carrying boundary: system of record versus derived is labelled, the tolerated replication anomalies are named, and no guarantee is claimed that was not bought (`data-intensive.md`)
- [ ] The tradeoff table names what each option sacrifices, not only what it provides
- [ ] A recommendation is made — not a menu handed back to the user
- [ ] The seam that preserves reversibility is identified
- [ ] A revisit trigger is written as an observable condition, not a date
- [ ] Anything owned by another skill or persona was handed over rather than re-decided
- [ ] The decision is recorded per `decisions.md`, and `document` is queued to update `docs/ARCHITECTURE.md` once it is implemented
