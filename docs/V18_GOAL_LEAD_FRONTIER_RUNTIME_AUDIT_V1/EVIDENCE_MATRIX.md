# Root Cause Evidence Matrix

## CSV schemas

### RUNTIME_POPULATION.csv
`cycle,checkpoint,location,prog_goal_count,prog_goal_ids,prog_frontier_count,prog_frontier_active,prog_frontier_deferred,dual_stall_class,goal_stall,activity_stall,ndm_commits,gd_count,lat_count,mp_count,director_goal_id,director_goal_keys,candidate_next_actions_count,progress_events_buf,natural_decision_frontier_set,related_store_keys,corbitt_house_entered_flag,in_basement_flag`

### DECISION_BINDING.csv
`index,decision_transaction_id,reasoning_id,decision_source,cycle,turn,location,action,target,goal_id,goal_ids,lead_id,lead_ids,frontier_id,expected_state_effect,observed_state_effect,selection_reason,binding_class`

### PROGRESS_EVENTS_SAMPLES.csv
`cycle_sample,progress_event_id,progress_type,progress_class,kind,goal_id,lead_id,frontier_id,goal_ids,lead_ids,frontier_ids`

---

| Root Cause Candidate | Observed Evidence | Contradicting Evidence | Strength | Conclusion |
|---|---|---|---|---|
| LEAD_RUNTIME_POPULATION_GAP | Zero production `LeadTracker.upsert` call sites; `high_value_leads` empty into KP/progression every decide | Unit tests successfully upsert leads | DIRECT_RUNTIME_EVIDENCE + STATIC_CODE_EVIDENCE | **CONFIRMED** |
| FRONTIER_RUNTIME_POPULATION_GAP | Frontier store size=0 all 60 cycles; zero production `upsert_frontier` call sites; Persistence=0 | Fixtures manually upsert and PASS | DIRECT + STATIC | **CONFIRMED** |
| GOAL_CONTEXT_BINDING_GAP | Director has `current_goal` text; `goal_id` empty; progress events goal_id empty; synthetic `default_goal` only | Narrative goal string exists | DIRECT + STATIC | **CONFIRMED** |
| GOAL_RUNTIME_POPULATION_GAP (absolute zero goals) | — | Director goal blob + default_goal tracker entry | — | **REJECTED** as absolute zero; **PARTIAL** for ID’d goals |
| FRONTIER_ACTION_BINDING_GAP | 0/173 frontier_id on commits | Requires frontiers to exist first | PERSISTED | **Downstream** of population gap |
| ACTION_EFFECT_BINDING_GAP | 0/173 expected/observed on ACTION_SELECTED | ASE module exists; fixtures use it | PERSISTED + STATIC | **STRONGLY_SUPPORTED** secondary gap |
| TRACE_EVENT_EMISSION_GAP | Progress events exist but lack G/L/F; ACTION_SELECTED lacks chain fields | Events themselves are emitted | PERSISTED | **STRONGLY_SUPPORTED** (emission incomplete, not absent) |
| METRIC_AGGREGATION_GAP | Recomputed classifier matches Lateral-all / GD=0 | Rates align with inputs | DERIVED | **REJECTED** as primary |
| Classifier bug (F) | Empty-context re-eval → Lateral | Would need GD links wrongly ignored | DERIVED + STATIC | **REJECTED** as primary |
| No goal-related actions (I) | — | Many basement_door / corbitt_basement actions in DECISION_BINDING | PERSISTED | **REJECTED** |
| P3 instant RESOLVED frontiers | — | No frontiers ever created | — | **REJECTED** |
| P4 ID transfer only | — | Store empty in checkpoints (Layer 2) | DIRECT | **REJECTED** |
| P5 aggregation only | — | Store empty | DIRECT | **REJECTED** |

## Evidence strength legend used

- DIRECT_RUNTIME_EVIDENCE: checkpoint `director_v2.progression_convergence`
- PERSISTED_EVENT_EVIDENCE: NDM telemetry ACTION_SELECTED / progress_events
- STATIC_CODE_EVIDENCE: ripgrep of production vs test call sites
- DERIVED_METRIC_EVIDENCE: classifier re-eval / rates
