# Decisions — Trade-offs, Reversibility, and ADRs

A decision is finished when someone who was not in the room can tell what was chosen, what it
cost, and what would change it. Anything short of that is a preference that happened to win.

## The trade-off table

The table is the analysis, not the presentation of a conclusion already reached. Build it from the
forces gathered in the procedure, one row per force that actually discriminates between the
options.

### Rules

- **Rows are forces, not features.** "Latency budget", "operational cost", "team fit" — not
  "modern", "flexible", "scalable". If a row does not distinguish the options, delete it; it is
  padding.
- **Every option must win something.** If one column wins every row, one of three things is true:
  the decision is obvious and needs no table, a real cost has been omitted, or the table was
  written after the conclusion. Check which before presenting it.
- **Score with evidence or mark it unknown.** A number with a source beats a rating. "Unknown"
  is a legitimate and useful cell — it points at the spike worth running.
- **Include the incumbent.** "Change nothing" is an option with real costs and real benefits, and
  it is the baseline the others must beat.
- **Name the sacrifice in prose.** The table compresses; one sentence after it should say plainly
  what the recommended option gives up. That sentence is the most-read line in the document.

### Shape

```markdown
| Force (weight) | Keep as is | Extract service | Async via events |
|---|---|---|---|
| Change coupling — 60% of features touch both (measured) | Poor | Good | Good |
| Read-after-write on the checkout path (hard requirement) | Satisfied | Satisfied | **Violated** |
| Peak load asymmetry — 40:1 read/write (measured) | Poor | Good | Good |
| Operational cost — no tracing today, 2 engineers | Good | Poor | Poor |
| Reversibility | n/a | Expensive door | Expensive door |

Recommendation: extract the service, and pay down tracing first.
Sacrificed: two engineers absorb a new on-call surface for a quarter. If that is not
affordable, the honest alternative is to keep as is and revisit in two quarters — not to
extract and hope.
```

Note what the third column does: a hard constraint eliminates it outright. Say so in the table
rather than scoring it as merely weaker — eliminated and worse are different findings.

## Reversibility

How much analysis a decision deserves is a function of what it costs to undo. Classify before
analysing, so effort lands where it matters.

| Class | Undo cost | Examples | Deserves |
|---|---|---|---|
| **Cheap door** | Hours to days | Library choice behind an interface, naming, internal module layout, log format, alert thresholds | Decide it and move. Analysis costs more than reversal. |
| **Expensive door** | Weeks to months | Extracting a service, sync versus async between two owners, adding a projection store, changing an event schema with live consumers | The full procedure and a written ADR. |
| **One-way door** | Effectively permanent | Datastore for a large dataset, event sourcing as the source of truth, a published external API, a data residency commitment, a partitioning key on a huge table | The full procedure, an explicit search for a seam that would make it reversible, and a named person accepting it. |

Two rules follow:

1. **Do not spend one-way-door analysis on cheap doors.** It is the most common waste in design
   review, and it teaches people that the process is theatre.
2. **Always look for the seam that downgrades the class.** Many one-way doors become expensive
   doors behind an interface, and many expensive doors become cheap ones. Finding that seam is
   usually worth more than getting the choice right.

## Deciding now versus deferring

Defer to the **last responsible moment** — the point past which deferring costs more than
deciding. Not the last possible moment.

Decide now when: the decision blocks work that cannot proceed without it; the cost of the seam
that would let you defer exceeds the cost of being wrong; the option set is shrinking (a
dependency is being deprecated, a contract is about to be published).

Defer when: a cheap seam exists; the deciding evidence is about to arrive (a load test, a pilot,
a hire); the reversibility class is cheap anyway.

**A deferral is a decision and gets recorded as one.** An ADR with status `Deferred` that names
the seam, the trigger for revisiting, and who is watching for it is a real output. An undocumented
deferral is just an open question that will be rediscovered under time pressure.

## Architecture Decision Records

ADRs live in `docs/adr/`, one file per decision, named `docs/adr/NNNN-short-slug.md` with a
zero-padded sequence. They are append-only in spirit: a decision that changes gets a new record
that supersedes the old one, and the old one stays with its status updated. The history is the
point — a directory where records get edited to stay correct loses the reasoning that made the
old choice sensible at the time.

This is why the `document` skill does not own ADRs: it documents current reality and explicitly
refuses to write aspirations or history. ADRs are the complement — they hold the *why*, including
for decisions later reversed. Once a decision is implemented, `document` updates
`docs/ARCHITECTURE.md` to describe the resulting structure, using its own Mermaid conventions.
The ADR keeps the reasoning; ARCHITECTURE.md keeps the shape.

### Status lifecycle

| Status | Meaning |
|---|---|
| `Proposed` | Written, under discussion, not yet agreed |
| `Accepted` | Agreed and being implemented or implemented |
| `Deferred` | Deliberately not decided, with a seam and a trigger recorded |
| `Superseded by NNNN` | A later record replaces this one. Never delete the original. |
| `Rejected` | Considered and declined. Worth keeping — it stops the same proposal recurring annually. |

### Template

```markdown
# NNNN. <Decision in imperative form: "Extract billing into its own service">

- Status: Proposed | Accepted | Deferred | Superseded by NNNN | Rejected
- Date: YYYY-MM-DD
- Deciders: <names>
- Reversibility: cheap door | expensive door | one-way door

## Context

The forces, with numbers and their sources. What problem forced this decision now, and what
constraints are non-negotiable. Mark unknowns as unknown — a reader a year from now needs to
know what you did not know.

## Options considered

Each option in a sentence or two, including the incumbent. For each rejected option, the
specific force or constraint that ruled it out — not a general impression.

## Decision

What was chosen, in one or two sentences, in the active voice.

## Consequences

### What this gives us
### What this costs us
Mandatory, and specific. New failure modes, new operational surface, capability given up,
staleness introduced, complexity added. A consequences section with nothing in this half means
the analysis is incomplete.

### What becomes harder to change
The seam that survives, and the one that does not.

## Revisit when

Observable conditions, not dates. See below.
```

### Revisit triggers

Date-based reviews ("revisit in six months") are not honoured, because nothing happens on the
date. Observable conditions get noticed, because someone is already watching the metric.

Write triggers as conditions with thresholds:

- Write throughput on the shared table exceeds N per second sustained
- The staleness window is breached in a way a user reports, more than once a quarter
- Team count on this component reaches three, or drops to zero
- The compensation path in the saga fires more than N times a month
- Any consumer needs read-after-write on the projected read model
- Cross-component release coordination is required more than once a month
- The deferral's seam is about to be crossed by planned work

Where the trigger maps to something measurable, say which metric or dashboard, and note that the
alerting for it belongs to `/sre`.

## Disagreement

- **Separate the disagreement type.** Different facts is a research problem — go get the number.
  Different weights on the same facts is a priorities problem and belongs to `/pm` or `/staff`.
  Different risk tolerance is a judgement call needing an owner. Conflating them produces long
  arguments that resolve nothing.
- **Write the strongest version of the opposing case** into the options section, not a weakened
  one. If the record misrepresents the alternative, the decision will be relitigated.
- **Disagree and commit, in writing.** Record who decided, that dissent existed, and what the
  dissenter expects to go wrong. If it does go wrong, that line is the revisit trigger and nobody
  has to reconstruct it from memory.
- **Escalate on deadlock, do not average.** Splitting the difference between two coherent
  architectures usually yields one that is worse than either.

## Anti-patterns

- **The rubber stamp.** Options invented to justify a foregone conclusion. The tell is a
  trade-off table where the recommended option wins every row, or where rejected options are
  described in a sentence while the chosen one gets a page.
- **All-upside consequences.** Covered above, and the single most common defect in real ADRs.
- **The essay.** Length is not rigour. If the forces are three lines and the prose is three pages,
  the analysis is thin and the writing is compensating.
- **Undated, unowned.** A record with no decider cannot be revisited, because nobody is
  accountable for watching the trigger.
- **The stale record edited into agreement.** Editing an old ADR to match what was later built
  destroys the reason the original made sense. Supersede it instead.
- **The decision nobody can find.** An ADR in a chat thread, a ticket comment, or a slide deck is
  not recorded. It goes in the repository, next to the code it constrains.
