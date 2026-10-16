# Goal Transition / Move Candidate 根本原因分析

## 総合判定

`GOAL_COMPLETION_DETECTION_ROOT_CAUSE`

より正確には、**礼拝堂のlocation objective completion判定が、現在操作不能な対象を未完了として数える問題**である。

Goal Managerは礼拝堂Goalを保持していない。active goalは一貫してシナリオ終端目標「悪霊の家を完了する」で、subgoalは `corbitt_basement_room2__corbitt_body__defeat` だった。Corbitt側の目標へ向いているため、H1「古い礼拝堂Goalの維持」は否定される。

Moveは生成後にfilterされたのではない。`location_objective_status=ACTIVE` によりtransition candidate生成分岐へ入らず、Availabilityへ到達する前に欠落した。

調査中に製品コード、Prompt、scenario、checkpointは変更していない。LLMも呼んでいない。

## 対象区間

- basement exit: cycle 30 / game turn 75 / `evt_000275_895b1d6981e57f540c6f`
- `FIRST_POST_CHAPEL_COMPLETION_STATE`: 上記イベント直後
- `FIRST_MISSED_MOVE_TURN`: cycle 30 / game turn 76 / `evt_000278_7b0a98cd323e79c2c5a0`
- stop point: cycle 35 / game turn 95 / checkpoint `cycle_000035`

地下脱出イベントで `chapel_cellar_entered: true → false` となった。直後に本来生成されるべき候補は `move / the_neighborhood` だが、次の行動は `search / cult_diary` だった。

## FIRST_POST_CHAPEL_COMPLETION_STATE

- cycle / game turn: 30 / 75
- event: `evt_000275_895b1d6981e57f540c6f`
- location: `chapel_of_contemplation`
- scene: `scene_001`
- actor: `pc_01`
- active goal: `悪霊の家を完了する`
- subgoal: `corbitt_basement_room2__corbitt_body__defeat`
- action phase after recomputation: `DISCOVER`
- location objective: `ACTIVE`
- basement state: surface (`chapel_cellar_entered=false`, scoped `in_basement=false`)
- combat: `INACTIVE`
- main chapel flags: `chapel_investigated=true`、`symbol_investigated=true`、`floorboards_examined=true`

## Scenario Objective

礼拝堂の唯一の出口は次の通り。

- source: `chapel_of_contemplation`
- destination: `the_neighborhood`
- prerequisite: `!in_basement`
- cycle 30 runtime: 条件成立
- `get_available_exits`: `the_neighborhood`を返す
- `corbitt_exterior`への最短の次step: `the_neighborhood`

Corbitt側の次の実質objectiveは、屋敷外観へ戻り、屋敷へ侵入し、最終的に `corbitt_basement_room2` で `corbitt_body`を倒すこと。scenario routeは礼拝堂→近隣→屋敷外観まで存在する。

### 礼拝堂対象の分類

- `chapel_secret_cellar`: ALREADY_COMPLETED。`chapel_investigated=true`。
- `chapel_ruins`: ALREADY_COMPLETED。同じ `chapel_investigated` を共有するalias相当。
- `white_symbol`: ALREADY_COMPLETED。`symbol_investigated=true`。
- `rotting_floorboards`: ALREADY_COMPLETED。`floorboards_examined=true`、地下進入・脱出済み。
- `skeletons_in_robes`: UNAVAILABLE / OPTIONAL。地上では `requires_flag=in_basement` 未達。
- `shelf_with_records`: UNAVAILABLE / OPTIONAL。地上では `requires_flag=in_basement` 未達。
- `cult_diary`: UNAVAILABLE。`found_diary` 未達で、対象自体が未出現。
- `grimoire_book_of_eibon`: UNAVAILABLE。`found_grimoire` 未達で、対象自体が未出現。

後半4件はtransitionの必須条件ではない。しかし現行 `derive_target_statuses` は `requires_flag` を見ず、すべて `UNSEEN` とする。これが `PHANTOM_REQUIREMENT` に相当する。

## Goal Timeline

cycle 25〜35を通して次の状態は不変。

- active goal: `悪霊の家を完了する`
- terminal event: `corbitt_basement_room2__corbitt_body__defeat`
- remaining requirements:
  - `flag:corbitt_body_encountered=true`
  - `location:corbitt_basement_room2`
  - `action:break/force/attack/use/push/kick/corbitt_body`
- goal candidate: 空

Goal分類は `GOAL_TRANSITIONED_CORRECTLY` とした。この実装はlocal objectiveごとのGoalを遷移させず、最初からglobal terminal goalを使う。GoalはすでにCorbitt討伐を指しており、礼拝堂に固定されていない。

## Remaining Requirements

Global goalの3 requirementは実際に未達であり、phantomではない。ただし遠方の終端条件であり、礼拝堂から出ることを禁止する条件でもない。

PhantomなのはGoal Managerのremaining listではなく、location objectiveが暗黙に「全objectがINVESTIGATED/EXHAUSTEDになるまで未完」と扱う4対象である。地上では操作不能なのに `UNSEEN` のため、locationを永続的に `ACTIVE` にする。

## Action Phase Timeline

- cycle 29: `EXECUTE`。地下脱出操作が存在。
- cycle 30〜35: すべて `DISCOVER`。
- `TRANSITION`到達: 0回。
- 分類: `NEVER_ENTERED_TRANSITION`

`derive_action_phase`は、locationが `SATISFIED/EXHAUSTED` なら `TRANSITION` を返す。しかし現行statusに `UNSEEN` が含まれるため `ACTIVE` となり、候補が空でも `DISCOVER` を返す。

## Candidate Pipeline

cycle 30 fixtureでの実際の段階は以下。

1. Global goal candidate: 0件。深い終端locationまで現在のunlock状態で完全経路を解決できない。
2. State-change candidate: 0件。
3. Unseen information candidate: 4件生成。
4. 先頭3件へ切り詰め: `skeletons_in_robes`、`shelf_with_records`、`cult_diary`。
5. Transition candidate creation: `location_objective_status=ACTIVE` のため実行されない。
6. Availability filtering: 上記3件をすべて `BLOCKED_STATE_CONFLICT` として除外。
7. Final candidate: 0件。
8. LLM-visible director candidate: 0件。

したがってMove分類は `NOT_CREATED`。`CREATED_AND_FILTERED` ではない。

## Move Candidate Analysis

cycle 30〜35のmove系Availability checkは0件。セッション最後のmove checkは礼拝堂到着時の `evt_000120_64621b4c1e8374fa4333` であり、地下脱出後には存在しない。

これはAction AvailabilityがMoveをBLOCKしたのではなく、上流でMoveが供給されていない直接証拠である。

## Scenario Route Analysis

- 礼拝堂→近隣: routeあり、runtime AVAILABLE。
- 礼拝堂→屋敷外観: 最短next stepは近隣。
- 礼拝堂→Corbitt地下室2: 現状態では完全経路解決不可。屋敷侵入flagによるgateがあるため。

即時離脱routeは正常なので `SCENARIO_ROUTE_RESOLUTION_ROOT_CAUSE` は否定する。Goal Managerが最終地点まで完全に到達可能でないとfrontier候補を返せない点は二次要因だが、local transition候補が生成されれば今回の礼拝堂離脱は成立する。

## Scene / Goal Consistency

- scene id: `scene_001`
- checkpointにscene objective、scene completion、scene next transition、scene lockの独立状態はない。
- Goal: Corbitt討伐
- location: 礼拝堂

Goalは将来の終端目標、sceneは汎用IDであり、古い礼拝堂Goalとの矛盾はない。`GOAL_SCENE_STATE_DIVERGENCE` は検出しなかった。

## SYSTEM_FORCED 9 Analysis

`system_forced=9` はcycle 30〜35だけの件数ではなく、セッション累積値だった。

- 全9件: cycle 12、21、22、25、29、30、31、32、33
- 地下脱出後: 4件
- 地下脱出後の4件はすべて `break / rotting_floorboards`
- 4件ともprogress 0
- Move候補: 全件pool内になし
- 分類: `MOVE_NOT_IN_POOL`

S4は空のdirector candidate poolからMoveを選べず、別系統の既知候補である床板操作を再利用した。

## no-progress Analysis

`no-progress=96` もセッション累積カウンタ。地下脱出後の対象区間では22行動すべてprogress 0だった。

- investigate: 13
- basement再進入系操作: 7
- wait: 2
- move: 0
- progress発生: 0

## 22 Post-Basement Actions

全22件は `post_basement_actions.json` に保存した。最初の10件は次のループを示す。

1. cult diary調査
2. 床板break（SYSTEM_FORCED）
3. chapel ruins再調査
4. 床板break
5. 床板break
6. 床板break（SYSTEM_FORCED）
7. 床板再調査
8. chapel ruins再調査
9. 地階の骸骨調査
10. 床板break（SYSTEM_FORCED）

すべてprogress 0で、Goal、Phase、candidate poolは変化しなかった。

## FIRST_MISSED_MOVE_TURN

- cycle / game turn: 30 / 76
- event: `evt_000278_7b0a98cd323e79c2c5a0`
- actual action: `search / cult_diary`
- expected move: `move / the_neighborhood`
- current location: `chapel_of_contemplation`
- phase: `DISCOVER`
- location objective: `ACTIVE`
- raw candidate: unavailableなsearch 3件
- final candidate: 0件
- route: `the_neighborhood` AVAILABLE
- stall before action: 20 / S4

## Fixture Result

cycle 30 checkpointから分析専用fixtureを作成した。checkpoint boundaryの `pending_action_id` はfixture内だけでnullに正規化し、元checkpointは変更していない。

### 実状態

- Goal: Corbitt討伐を指す
- Action Phase: `DISCOVER`
- Location objective: `ACTIVE`
- raw Move: なし
- final Move: なし

### 診断用counterfactual

未達 `requires_flag` を持つ4対象を、location completion判定上だけ `UNAVAILABLE` とした。

- Location objective: `EXHAUSTED`
- raw candidate: `move / the_neighborhood`
- final candidate: `move / the_neighborhood`
- Availability: `AVAILABLE`
- Action Phase: `TRANSITION`

この結果により、routeやAvailabilityを変更せず、対象status分類だけでMoveが復活することを確認した。

## Root Cause

`ProgressionPolicy.derive_target_statuses` がobjectの `requires_flag` を評価せず、現在操作不能な対象を `UNSEEN` と分類する。

その `UNSEEN` が `derive_location_objective_status` を `ACTIVE` に固定し、`add_progression_candidates` のtransition候補生成条件を満たさない。Moveはこの地点で初めて失われる。

## Amplifiers

1. Unavailableな情報候補をAvailabilityより前に先頭3件へ切り詰めるため、candidate枠がすべて無効候補で埋まる。
2. Global Goal routeは、将来gateを含む最終地点への完全経路が現在解決できないと、到達可能frontier候補を返さない。
3. Final candidateが空のS4 fallbackは既知の床板操作を再利用し、location completionを再評価できる新しい状態変化を起こさない。

## Symptoms

- Action Phase `DISCOVER`固定
- Move Availability check 0
- 地下脱出後22行動すべてno-progress
- SYSTEM_FORCED累積9、うち地下脱出後4
- max stagnation 42
- cycle 35でも礼拝堂滞在

## Evidence

- cycle 30/35 director state: location objective `ACTIVE`、final candidates空
- target statuses: 地上で操作不能な4対象が `UNSEEN`
- scenario runtime: `the_neighborhood` exitはAVAILABLE
- fixture actual: Moveなし
- fixture counterfactual: 同じflags/routeでMove生成・Availability PASS
- post-exit move系Availability event: 0

## 原因候補ランキング

### 1. Location completionがunavailable targetを未完扱いする

- confidence: 0.99
- module: `ProgressionPolicy.py`
- evidence: fixture counterfactualでMoveとTRANSITIONが復活
- counter-evidence: なし

### 2. CandidateをAvailability前に3件へ切り詰める

- confidence: 0.80（増幅要因）
- module: `ProgressionPolicy.py`
- evidence: raw先頭3件がすべてBLOCKされ、4件目以降を評価できない
- counter-evidence: 今回はMove生成条件自体に入っていないため単独原因ではない

### 3. Global goal routeが到達可能frontierを返さない

- confidence: 0.65（二次要因）
- module: `ProgressDirectorV2.py`
- evidence: basement room2への完全routeはgateで空、Goal candidateも空
- counter-evidence: local transition candidateが正常なら礼拝堂離脱には影響しない

## 修正候補

### 1. `GOAL_COMPLETION_SYNC_FIX`（推奨）

- target: `ProgressionPolicy.derive_target_statuses` / location completion判定
- behavior: unmet `requires_flag` の対象を `UNAVAILABLE` と分類し、現在locationからの離脱を妨げる未完了対象として数えない。required/optional metadataがある場合はそれも尊重する。
- why: 根本原因を最初の誤分類地点で直す。
- regression risk: 中。将来unlockされる必須対象を早期に無視しない設計が必要。
- generality: 高。状態依存objectを持つ全scenarioに適用可能。

### 2. `POST_OBJECTIVE_MOVE_CANDIDATE_FIX`

- target: progression candidate generation
- behavior: availableな進行候補が0件で有効exitがある場合、locationがACTIVEでもexit Moveをfallback候補として追加する。
- why: status誤分類が残っても完全膠着を防げる。
- regression risk: 中〜高。重要な未調査対象を残して早期離脱する可能性。
- generality: 高。
- recommendation: 防御策として案1の後に検討。

### 3. Candidate filter順序の修正

- target: `add_progression_candidates` / Availability filtering
- behavior: raw candidateを3件へ切る前にAvailabilityを評価し、BLOCK候補が有効候補の枠を消費しないようにする。
- why: 無効候補によるcandidate starvationを防ぐ。
- regression risk: 低〜中。候補優先順とログ件数が変わる。
- generality: 高。
- recommendation: 案1と同時または直後の回帰対象。

## 推奨次工程

次フェーズは `GOAL_COMPLETION_SYNC_FIX` とする。

まず今回の `cycle30_fixture.json` を対象テスト化し、以下を期待値とする。

1. 地上でunavailableな地階対象がlocation completionを妨げない。
2. `move / the_neighborhood` がraw候補に現れる。
3. Availability後もMoveが残る。
4. Action Phaseが `TRANSITION` になる。
5. 地下にいる間は地階対象を引き続き探索候補として扱える。
6. Corbitt固有ifを追加しない。

修正後はfixture回帰を先に行い、その後、新しい評価chainで礼拝堂離脱まで局所LLM評価する。
