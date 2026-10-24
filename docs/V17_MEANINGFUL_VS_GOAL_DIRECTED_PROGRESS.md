# V17 Meaningful vs Goal-Directed Progress

## Official vs audit rates

| Metric | Value | Source |
|---|---|---|
| MEANINGFUL_PROGRESS_RATE | **0.9950** | NDM KP `meaningful_progress_this_cycle` (201/202) |
| GOAL_DIRECTED_PROGRESS_RATE | **0.1000** | read-only audit (see definition) |
| LATERAL_EXPLORATION_PROGRESS_RATE | **0.7000** | read-only audit |
| MAX_GOAL_DIRECTED_NO_PROGRESS_STREAK | **35** | consecutive checkpoint cycles without GD action |
| MEANINGFUL_PROGRESS_INFLATION | **true** | |

## Classification method (no hidden solution)

**Meaningful (runtime):** any progress event kind in `MEANINGFUL_PROGRESS_KINDS` / V17 progress_types (`NEW_LOCATION`, `NEW_FACT`, `OBJECT_STATE_CHANGE`, …).

**Goal-directed (audit):** action addresses an **already-visible unresolved** critical lead/blocker derived from observed flags only, e.g.:

- `basement_accessible=true` AND planks not broken → `move/corbitt_basement`, `search/basement_planks`, `search/scattered_junk`, knife-related
- basement door **not yet** unlocked → door actions
- Post-unlock repeated `basement_door` search is **not** counted GD (blocker already cleared)

**Not used:** “correct path”, “near ending”, author route, future required events.

## Progress event type picture

Buffered union across checkpoints (`progress_events` maxlen=64 ⇒ early undercount):

| progress_type | class |
|---|---|
| NEW_LOCATION (dominant) | LATERAL_EXPLORATION |
| OBJECT_STATE_CHANGE | INFORMATION_OR_STATE |
| NEW_FACT | INFORMATION_OR_STATE |
| OBJECTIVE_ADVANCEMENT | rare / effectively absent in buffers |

All buffered events use `progress_class=MEANINGFUL`. There is **no** runtime `GOAL_DIRECTED` class.

## Inflation mechanism

1. Location changes (including revisits) emit `NEW_LOCATION`.
2. Object/flag noise emits `OBJECT_STATE_CHANGE` / `NEW_FACT`.
3. KP marks `meaningful_progress_this_cycle=true` → trend `advancing`.
4. Intervention / S-escalation resets (`reason=meaningful_progress`).
5. Unresolved basement-plank lead can sit idle for dozens of cycles while rate stays ~1.0.

Hence meaningful rate **masks** goal drought (`MAX_GOAL_DIRECTED_NO_PROGRESS_STREAK=35`).

## Mapping to requested buckets

| Bucket | V17 evidence |
|---|---|
| INFORMATION_PROGRESS | NEW_FACT present |
| EXPLORATION_PROGRESS | NEW_LOCATION dominant; upstairs/GF revisits |
| STATE_PROGRESS | OBJECT_STATE_CHANGE; **not** plank examined/broken |
| RESOURCE_PROGRESS | not dominant |
| HYPOTHESIS_PROGRESS | not evidenced in KP |
| GOAL_DIRECTED_PROGRESS | ~10% of cycles (audit) |
| TERMINAL_PROGRESS | 0 (no defeat/clear) |

## Ideal separation (design hypothesis only — not implemented)

```text
Meaningful Progress
+ Goal-Directed Progress
+ Exploration Value
```

Convergence pressure candidate (not S4-force): long GD drought → PL self-review → lead reorder → soft KP nudge.
