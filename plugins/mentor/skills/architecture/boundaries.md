# Boundaries — Finding the Seams

A boundary is not a line on a diagram. It is a claim that **two things can change
independently**. Everything here exists to test that claim before you commit deployment topology,
team structure, and data ownership to it.

The order matters: find the boundary first, then pick the style from `styles.md` that fits it. A
style chosen first will bend the boundaries to suit itself.

## The seven tests

Run every proposed boundary through all seven. Tests 2 and 3 are **hard** — a boundary that fails
either is not viable and should be dropped, not mitigated. The rest are trade-offs to be named and
weighed.

### 1. Change coupling — do these change together?

If a typical feature touches both sides, the boundary is in the wrong place. This is the
strongest single signal and the only one you can measure from evidence rather than opinion.

```sh
# Files most often changed in the same commit as a candidate module.
# High counts outside the module are change coupling the boundary would cut through.
git log --since=12.months --format=%H -- src/billing \
  | while read -r c; do git show --name-only --format= "$c"; done \
  | awk 'NF' | sort | uniq -c | sort -rn | head -30
```

Read it with two caveats: exclude mechanical mega-commits (formatting sweeps, dependency bumps)
which correlate everything with everything, and remember that a shared file appearing everywhere
may be a genuine cross-cutting concern rather than a boundary violation.

**Verdict** — a candidate whose top co-changing files sit mostly on the other side of the
proposed line has failed. Move the line to where the co-change already is.

### 2. Data ownership — is there exactly one writer? (hard)

Every dataset has exactly one component that may write it. Everyone else reads through a
contract, or holds a replica they do not mutate.

Two writers is not a boundary. It does not matter how the components are packaged, deployed, or
drawn — if both write the same rows, neither can change the schema, neither can enforce an
invariant, and the boundary is decorative.

Label each dataset **system of record** or **derived** while you are here. Derived data is defined
by being rebuildable from its source; if the copy on the far side of the boundary cannot be
reconstructed, it is a second system of record with no owner. See `data-intensive.md`.

**Verdict** — name the single writer for every dataset the boundary touches, and say which side
holds derived data. If you cannot, the boundary does not exist yet.

### 3. Transactional scope — does an invariant span the line? (hard)

List the invariants that must hold. For each, ask whether it must be true *immediately* or may be
true *eventually*, and get that answer from the business, not from the implementation.

- **Must be immediate, and spans the line** → the boundary is wrong, or you are buying a saga and
  the compensation logic that comes with it. See the saga entry in `styles.md`, and check whether
  merging the two sides is the cheaper answer.
- **May be eventual** → the boundary is viable, but "eventual" is not yet an answer. Replication
  lag is three distinct anomalies — read-your-writes, monotonic reads, consistent prefix reads —
  and a consumer survives them independently. Name which ones this boundary tolerates, per
  `data-intensive.md`. A user-facing consumer almost always needs read-your-writes, and that is
  the one nobody asks about until it arrives as "it did not save".

Note what *cannot* be bought: inside one database, a concurrency anomaly is fixable by raising the
isolation level. Across a boundary there is no isolation level to raise. An invariant spanning the
line has three honest options — move it inside one owner, detect and reconcile the violation, or
buy coordination — and no fourth where it holds because everyone is careful.

**Verdict** — an unexamined "eventually is probably fine" is the most expensive assumption in
distributed design. Get the specific anomalies confirmed and written down.

### 4. Failure independence — can one side fail alone?

For each direction, ask what happens when the other side is unavailable. Three honest answers:

| Answer | What it means |
|---|---|
| It keeps working, degraded, with a defined fallback | Real independence. The boundary buys reliability. |
| It fails too | The boundary buys nothing on this axis. Possibly fine, but do not claim resilience for it. |
| Nobody knows | The most common answer, and the one to resolve before shipping. |

A synchronous call with no fallback creates availability coupling: the caller's availability is
now the product of both. Chain four of those and a comfortable number becomes an uncomfortable
one.

**Verdict** — either name the fallback, or stop describing the split as a reliability improvement.

### 5. Chattiness — how many crossings per user action?

Count the round trips for the most common user action, and for the worst one. One or two is
usually fine. Four or more, especially in a chain rather than in parallel, means the boundary cuts
through something that wanted to stay together.

**Verdict** — high crossing counts do not call for caching or batching first. They call for
re-examining the line.

### 6. Contract — can you state the interface without leaking internals?

Write the interface down. If you cannot describe it without referring to the other side's tables,
enum values, internal states, or field ordering, then it is not an interface; it is a window into
an implementation, and every internal change will break a consumer.

**Verdict** — if the contract only makes sense to someone who has read both codebases, the
boundary is not real yet.

### 7. Team — can one team own it end to end?

One team should be able to change, test, deploy, and operate the component without waiting on
another. Conway's law is a description of what will happen, not advice.

More components than teams means individuals context-switch across several, and each gets less
attention than it needs. More teams than components means contention on the same code and release
path.

**Verdict** — if the answer requires two teams to coordinate for a routine change, the boundary
does not match the organisation, and one of the two will have to move.

## Where boundaries genuinely belong

| Cut along | Rationale | Watch for |
|---|---|---|
| **Bounded context** — a subdomain with its own consistent language | The strongest basis. Where the same word means different things (an "order" in fulfilment versus in billing), there is a real seam and a translation to make explicit. | Contexts asserted from a diagram rather than discovered from how the business actually talks. |
| **Aggregate** — the smallest unit with a transactional invariant | Defines the floor: a boundary can never cut *inside* an aggregate, because the invariant would span it. | Aggregates drawn so large they become the whole domain, which tells you nothing. |
| **Volatility** — parts that change on very different cadences | Isolating a fast-changing part from a stable one lets each move at its own speed. | Cadence differences that reflect current project focus rather than intrinsic rate of change. |
| **Scaling profile** — parts with genuinely different load curves | The clearest economic argument for a split, and measurable. | Asserted asymmetry. Measure it; the intuition is often wrong. |
| **Trust boundary** — a change in who or what is trusted | Often forces a boundary the other tests would not justify. Non-negotiable when it applies. | Deciding this alone. Bring in `/security-architect`. |
| **Data lifecycle** — different retention, residency, or classification | Regulatory lines and retention rules are easier to enforce at a component edge than inside one. | Conflating classification with volume; they are different arguments. |

## Where boundaries do not belong

- **By technical layer.** An API component, a logic component, a data component. Every feature
  crosses every boundary, so nothing changes independently and you have maximised coordination
  while calling it separation of concerns.
- **By entity or table.** One component per noun. The boundaries follow the schema instead of the
  behaviour, invariants spanning two nouns have nowhere to live, and orchestration leaks into
  callers.
- **By team convenience at a point in time.** Team structure changes faster than architecture, and
  a boundary drawn around last quarter's org chart outlives it awkwardly.
- **Around a shared utility component.** A component every other one calls synchronously is a
  single point of failure with maximal fan-in. Shared *code* is usually the right answer for
  shared logic; a shared *component* needs the same seven tests as any other, and typically fails
  several.
- **Wherever the code already happens to be split.** An existing package layout is evidence of a
  past decision, not of a good boundary. Test it like any other candidate.

## Techniques for finding boundaries

**Co-change analysis.** The command above, run over the modules you suspect. The most objective
input available, and usually the most surprising.

**Dependency cycles.** Any cycle between candidate modules is a boundary violation by definition —
if A depends on B and B on A, they cannot change independently. Find the cycles first; they mark
either a boundary in the wrong place or a missing third module holding the shared concept.

**Language differences.** Where the business uses the same word for two different things, or two
words for one thing, there is a context boundary. This is a listening exercise, and it costs an
hour rather than a rewrite.

**Invariant inventory.** List every rule that must always hold, and which data it touches. The
inventory alone eliminates most candidate boundaries before any diagram is drawn.

**Load and cardinality measurement.** Before claiming divergent scaling, get the numbers: requests
per second per endpoint, row counts, growth rate, read/write ratio. Divergent scaling is the
easiest argument to make and the easiest to be wrong about.

## Building a seam you can move

The value of a seam is that it converts an irreversible decision into a deferred one. Three
things make a boundary movable later, and the third is the one usually skipped:

1. **An explicit interface** — the other side calls a named contract, not internals. Enforced
   mechanically (import rules, module visibility, lint) rather than by review.
2. **No shared mutable state** — separate schemas or clearly owned tables, even inside one
   database. Separate schemas in one database is the cheapest genuinely useful step available.
3. **A separate data path** — the extracting side can read its own data without joining across the
   line. If extraction requires unpicking a join, the seam is notional.

With all three, extraction is a deployment and migration exercise. With only the first, it is a
redesign. That difference is the entire practical value of the modular monolith.

## Contracts across the boundary

Once the boundary is real, its contract is published — treat it as such regardless of whether the
consumer is another team or the same one.

- **Both directions, at once.** *Backward* compatible means new code reads old data; *forward*
  compatible means old code reads data written by new code. A rolling upgrade runs both versions
  simultaneously, so both are required together, and the demands differ depending on whether the
  data flows through a database, a service call, or an async message — `data-intensive.md` has the
  breakdown, including the silent data loss when old code rewrites a record containing a field it
  does not know about.
- **Additive-only changes are safe.** New optional fields, new endpoints, new event types. Removing
  a field, renaming one, narrowing a type, or adding a required field are all breaking.
- **Tolerant reader.** Consumers ignore unknown fields and do not depend on ordering or on the
  absence of a field. This one rule prevents most avoidable breakage.
- **Version when you must break.** Run both versions concurrently, migrate consumers, then
  withdraw the old one on a stated schedule. A breaking change with no overlap window is an
  outage with a plan.
- **Events are contracts too**, and harder ones — the consumers may be unknown and, with event
  sourcing, the old events are permanent. Version them from the first day, not the first break.
- **State the guarantees explicitly**: ordering, delivery (at-least-once means idempotent
  consumers, always), and staleness. An unstated guarantee will be assumed, and the assumption
  will be the strongest one.

## Sharing data across the boundary

Exactly three options, and the choice is architectural rather than incidental:

| Option | Consumer gets | Costs |
|---|---|---|
| **Query the owner** | Current, consistent state | Availability and latency coupling; read load lands on the owner |
| **Replicate via events** | A local, stale replica it can serve independently | Inherits all three replication anomalies; the event becomes a contract; at-least-once delivery makes consumer idempotence mandatory, not optional |
| **Batch copy** | A periodic snapshot | Freshness limited to the window; simplest to operate and reason about |

Pick per relationship, not once for the whole system. Write down which replication anomalies the
consumer accepts, not a single staleness figure. Pipeline mechanics belong to `/data`; which of the three, and why, belongs here.

## Moving a boundary that already exists

Boundaries are wrong sometimes. Moving one is normal work, and there are three established ways
to do it without a rewrite:

- **Strangler fig** — stand the new boundary alongside the old, route traffic across incrementally
  by capability, and retire the old path when nothing routes to it. The default for anything
  live.
- **Branch by abstraction** — introduce the interface first, move both implementations behind it,
  switch, then delete. Best when the change is internal and the seam does not exist yet.
- **Parallel run** — execute both paths, compare outputs, and cut over only when they agree for a
  representative period. Reserved for boundaries where being wrong is expensive and correctness is
  checkable — pricing, billing, risk.

In all three, the sequencing rule is the same: **move the data ownership last**. Reroute reads,
then writes, then migrate the data. Migrating the data first leaves both sides writing to a
dataset neither owns, which is exactly the state test 2 exists to prevent.
