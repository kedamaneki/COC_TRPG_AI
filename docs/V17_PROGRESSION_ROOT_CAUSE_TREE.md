# V17 Progression Root Cause Tree

## Tree (evidence-backed)

```text
progress_types treat NEW_LOCATION / OBJECT_STATE_CHANGE as MEANINGFUL
        ↓
KP meaningful_progress_this_cycle ≈ always true (201/202), trend=advancing
        ↓
intervention / S-level reset (no S4); stall escalation suppressed
   concurrently:
goal object stuck at 「悪霊の家」 with empty requirements
KP unresolved_leads=[] and available_meaningful_frontiers=[] (202/202)
        ↓
GOAL_CONVERGENCE_SIGNAL_GAP (no explicit GD progress channel)
        ↓
continuity candidates still list basement_planks / move basement
but scores flat / often ignored (critical top ignored 17/17)
        ↓
FIRST_CONVERGENCE_DIVERGENCE @ C9:
leave basement after C8 without plank resolution
        ↓
ground_floor local optimum (cupboard / unlocked door / passage)
        ↓
optional ACTION_TO_STATE_EFFECT gap:
basement_planks searched ×10 never flips examined/broken
        ↓
final battle never reached by C60
```

## Primary

```text
PRIMARY_ROOT_CAUSE =
MEANINGFUL_PROGRESS_INFLATION + GOAL_CONVERGENCE_SIGNAL_GAP
allowing lateral exploration to dominate after abandoning the
visible unresolved basement-planks lead post-C8.
```

## Secondary

1. `FRONTIER_PRIORITIZATION_GAP` — flat continuity scores; novelty/local targets compete with critical cand.  
2. `FRONTIER_TO_ACTION_GAP` — critical top candidate never selected when present (17/17).  
3. `ACTION_TO_STATE_EFFECT_GAP` — repeated `basement_planks` search without state advancement (contrast V13 `wall_planks` path).  
4. `STALL_CLASSIFICATION_GAP` — director streak rises while KP meaningful resets intervention.  
5. `GOAL_TO_LEAD_GAP` / `LEAD_TO_FRONTIER_GAP` — KP lead/frontier lists empty despite continuity candidates.

## Failure interpretation tags

```text
MEANINGFUL_PROGRESS_INFLATION
GOAL_CONVERGENCE_SIGNAL_GAP
FRONTIER_PRIORITIZATION_GAP
STALL_CLASSIFICATION_GAP
MULTI_COMPONENT
```

(Not primary: pure `SCENARIO_FRONTIER_GAP` — candidates existed. Not sole: `NDM_DECISION_POLICY_GAP`.)

## V18 fix scope (design only)

```text
V18_FIX_SCOPE = MULTI_COMPONENT_FIX
```

Likely design packages (names only):

- `PROGRESS_SEMANTICS_FIX` — separate Meaningful / Goal-Directed / Exploration  
- `GOAL_CONVERGENCE_LAYER` — GD drought → self-review / soft nudge (not forced S4, not hidden-solution score)  
- `FRONTIER_PRIORITY_FIX` — surface unresolved visible leads into KP frontier set; persistence  
- investigate `ACTION_TO_STATE_EFFECT` for plank target mapping as scenario/adaptation subfix  

**Out of scope for first guess:** raise `goal_relevance` weight alone; railroad correct frontier; score hidden solutions.

```text
V18_READY = false
RECOMMENDED_NEXT_STEP = V18_PROGRESSION_CONVERGENCE_FIX_DESIGN_REQUIRED
```
