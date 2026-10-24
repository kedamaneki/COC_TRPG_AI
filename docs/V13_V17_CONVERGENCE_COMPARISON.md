# V13 vs V17 Convergence Comparison

**V13** = Known-Good success path（成功比較対象。唯一の正解ルートではない。同じ行動順の再現を要求しない）。  
**V17** = NDM-healthy non-completion.  
比較するのは convergence characteristics のみ。

## Outcome

| Field | V13 | V17 |
|---|---|---|
| completed / phase | true / clear | false / investigation |
| final cycle / turn | 25 / 65 | 60 / 179 |
| final location | corbitt_basement_room2 | corbitt_ground_floor |
| corbitt_defeated | true | false |
| max_no_progress (result) | 55 | 169 |

## Milestone table

| Milestone | V13 | V17 | Difference |
|---|---|---|---|
| first basement arrival | **C10** | **C8** | V17 earlier |
| leave basement soon after | C11 (brief) | **C9** | V17 leaves immediately |
| return / stick to basement plank work | C13 `wall_planks` | intermittent visits; rarely sticks | V17 weak persistence |
| planks examined | **C14** | **never** | critical |
| planks broken | **C21** | **never** | critical |
| upper-floor major clues | C16–19 | C10–15 then late revisits | both explore upstairs |
| return to basement for climax | C21–24 | never sustained | V17 fails |
| final battle trigger | **C25** | **none** | |
| clear | C25 | none | |

## Convergence characteristic (what to copy conceptually)

V13 after first basement:

1. Leaves briefly, **returns**.
2. Focuses plank-related target (`wall_planks` / listen) until `basement_planks_examined=true`.
3. Later breaks planks (`broken=true` by C21).
4. Stays basement-side until boss/clear at C25.

V17 after first basement:

1. Leaves at C9 to ground floor.
2. Top cand for planks is repeatedly **ignored** (17/17 critical-top ignores).
3. Dominates with cupboard / already-unlocked basement_door / hidden_passage / GF moves.
4. Searches `basement_planks` ×10 **without** examined/broken flag flips.
5. Hits cycle cap still on ground floor.

## FIRST_CONVERGENCE_DIVERGENCE

Not the first micro action difference (both enter house; V17 even reaches basement earlier).

```text
FIRST_CONVERGENCE_DIVERGENCE =
cycle = 9
event = leave_basement_without_plank_resolution
reason =
  C8: loc=corbitt_basement, basement_accessible=true,
      top continuity candidate=search/basement_planks,
      selected path does not resolve planks.
  C9: loc=corbitt_ground_floor, top cand=storage_room1_cupboard;
      thereafter lateral GF loops dominate; planks remain unresolved to C60.
```

This is the first branch that **materially changes goal convergence probability** under observed lead/frontier behavior.

## Comparison metrics (same concepts only)

| Metric | V17 | V13 note |
|---|---|---|
| GOAL_DIRECTED_PROGRESS_RATE (audit def.) | 0.10 | not identically instrumented pre-NDM; V13 shows plank flag progress by C14/C21 |
| MEANINGFUL_PROGRESS_RATE (V17 NDM) | 0.995 | V13 lacked same KP telemetry |
| FINAL_BATTLE | none | C25 |
| LOCATION_REVISIT_RATE | 0.7619 (V17; 1 − 5 unique / 21 visits) | V13 also revisits but converges |

Do **not** treat V13 action order as a script to reproduce.
