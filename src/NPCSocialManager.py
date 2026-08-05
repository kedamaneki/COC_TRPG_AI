"""
NPC ロールプレイおよび交渉技能（説得・言いくるめ・威圧・魅惑・心理学）の連動エンジン。
CoC 7版クイックスタート準拠の技能ロール + 関係性更新 + 秘密開示。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from expression_evaluator import SafeExpressionEvaluator
from DiceEngine import SuccessLevel, is_success_level

# 交渉・社交技能
SOCIAL_SKILLS = frozenset({
    "説得", "言いくるめ", "威圧", "魅惑", "心理学",
    "信用", "母国語",
})

SOCIAL_ACTION_IDS = frozenset({
    "talk", "speak", "chat", "converse", "対話", "会話", "話す",
    "negotiate", "persuade", "intimidate", "charm", "fast_talk",
    "psychology", "insight",
    "説得", "言いくるめ", "威圧", "魅惑", "心理学",
})

ACTION_TO_DEFAULT_SKILL = {
    "persuade": "説得",
    "説得": "説得",
    "fast_talk": "言いくるめ",
    "言いくるめ": "言いくるめ",
    "intimidate": "威圧",
    "威圧": "威圧",
    "charm": "魅惑",
    "魅惑": "魅惑",
    "psychology": "心理学",
    "insight": "心理学",
    "心理学": "心理学",
    "negotiate": "説得",
    "talk": "",
    "speak": "",
    "chat": "",
    "converse": "",
    "対話": "",
    "会話": "",
    "話す": "",
}

RELATIONSHIP_ORDER = ("hostile", "uncooperative", "neutral", "cooperative")
RELATIONSHIP_ALIASES = {
    "hostile": "hostile",
    "敵対": "hostile",
    "敵対的": "hostile",
    "uncooperative": "uncooperative",
    "非協力": "uncooperative",
    "非協力的": "uncooperative",
    "neutral": "neutral",
    "中立": "neutral",
    "cooperative": "cooperative",
    "協力": "cooperative",
    "協力的": "cooperative",
    "friendly": "cooperative",
    "友好": "cooperative",
}
RELATIONSHIP_LABELS = {
    "hostile": "敵対的",
    "uncooperative": "非協力的",
    "neutral": "中立",
    "cooperative": "協力的",
}

# 関係性 → 交渉ロールへのボーナス／ペナルティ・ダイス（ネット）
RELATIONSHIP_DICE_MOD = {
    "hostile": {"bonus": 0, "penalty": 2, "difficulty": "hard"},
    "uncooperative": {"bonus": 0, "penalty": 1, "difficulty": "regular"},
    "neutral": {"bonus": 0, "penalty": 0, "difficulty": "regular"},
    "cooperative": {"bonus": 1, "penalty": 0, "difficulty": "regular"},
}


def normalize_relationship(value, default="neutral") -> str:
    raw = str(value or default).strip().lower()
    if raw in RELATIONSHIP_ALIASES:
        return RELATIONSHIP_ALIASES[raw]
    jp = str(value or "").strip()
    if jp in RELATIONSHIP_ALIASES:
        return RELATIONSHIP_ALIASES[jp]
    return default if default in RELATIONSHIP_ORDER else "neutral"


def relationship_rank(status: str) -> int:
    status = normalize_relationship(status)
    try:
        return RELATIONSHIP_ORDER.index(status)
    except ValueError:
        return RELATIONSHIP_ORDER.index("neutral")


def shift_relationship(status: str, delta: int) -> str:
    idx = max(0, min(len(RELATIONSHIP_ORDER) - 1, relationship_rank(status) + int(delta)))
    return RELATIONSHIP_ORDER[idx]


def is_social_action(action_id: str, skill_name: str = "") -> bool:
    action = str(action_id or "").lower().strip()
    skill = str(skill_name or "").strip()
    if action in SOCIAL_ACTION_IDS:
        return True
    if any(s in skill for s in SOCIAL_SKILLS):
        return True
    return False


def is_casual_talk(action_id: str, skill_name: str = "") -> bool:
    """ダイスなしの雑談・挨拶。"""
    action = str(action_id or "").lower().strip()
    skill = str(skill_name or "").strip()
    if skill and any(s in skill for s in SOCIAL_SKILLS):
        return False
    return action in {
        "talk", "speak", "chat", "converse", "対話", "会話", "話す",
    }


def resolve_social_skill_name(action_id: str, skill_name: str = "") -> str:
    skill = str(skill_name or "").strip()
    if skill:
        for known in SOCIAL_SKILLS:
            if known in skill or skill in known:
                return known
        return skill
    action = str(action_id or "").strip()
    mapped = ACTION_TO_DEFAULT_SKILL.get(action.lower()) or ACTION_TO_DEFAULT_SKILL.get(action)
    return mapped or "説得"


class NPCSocialManager:
    """NPC の関係性・秘密・交渉解決を担当する。"""

    def __init__(self, char_mgr):
        self.char_mgr = char_mgr

    def get_npc(self, npc_id: str) -> Optional[dict]:
        char = self.char_mgr.characters.get(npc_id)
        if not char or not char.get("profile", {}).get("is_npc", False):
            return None
        return char

    def ensure_social_session(self, npc_id: str) -> dict:
        npc = self.get_npc(npc_id)
        if not npc:
            return {}
        social = npc.setdefault("session_social", {})
        if "relationship_status" not in social:
            base = (
                npc.get("relationship_status")
                or npc.get("profile", {}).get("relationship_status")
                or "neutral"
            )
            social["relationship_status"] = normalize_relationship(base)
        social.setdefault("revealed_secrets", [])
        social.setdefault("dialogue_count", 0)
        return social

    def get_relationship(self, npc_id: str) -> str:
        social = self.ensure_social_session(npc_id)
        return normalize_relationship(social.get("relationship_status", "neutral"))

    def set_relationship(self, npc_id: str, status: str) -> str:
        social = self.ensure_social_session(npc_id)
        social["relationship_status"] = normalize_relationship(status)
        self.char_mgr.save_data()
        return social["relationship_status"]

    def get_personality(self, npc_id: str) -> str:
        npc = self.get_npc(npc_id)
        if not npc:
            return ""
        profile = npc.get("profile") or {}
        return str(
            npc.get("personality")
            or profile.get("personality")
            or "\n".join(str(n) for n in (npc.get("roleplay_notes") or [])[:2])
            or npc.get("memo")
            or ""
        ).strip()

    def get_secrets(self, npc_id: str) -> Dict[str, dict]:
        npc = self.get_npc(npc_id)
        if not npc:
            return {}
        secrets = npc.get("secrets") or {}
        if isinstance(secrets, list):
            # 配列形式を辞書へ
            out = {}
            for i, item in enumerate(secrets):
                if isinstance(item, dict):
                    sid = str(item.get("id") or f"secret_{i+1:02d}")
                    out[sid] = item
                else:
                    out[f"secret_{i+1:02d}"] = {"content": str(item), "reveal_condition": "True"}
            return out
        return dict(secrets) if isinstance(secrets, dict) else {}

    def get_revealed_secret_ids(self, npc_id: str) -> List[str]:
        social = self.ensure_social_session(npc_id)
        return list(social.get("revealed_secrets") or [])

    def mark_secret_revealed(self, npc_id: str, secret_id: str) -> None:
        social = self.ensure_social_session(npc_id)
        revealed = social.setdefault("revealed_secrets", [])
        if secret_id not in revealed:
            revealed.append(secret_id)
            self.char_mgr.save_data()

    def build_npc_prompt_block(self, npc_id: str, *, include_secrets: bool = True) -> str:
        """KP 向けの NPC RP 注入ブロック。"""
        npc = self.get_npc(npc_id)
        if not npc:
            return ""
        name = npc.get("profile", {}).get("name", npc_id)
        personality = self.get_personality(npc_id)
        rel = self.get_relationship(npc_id)
        rel_label = RELATIONSHIP_LABELS.get(rel, rel)
        lines = [
            f"【NPCロールプレイ指定: {name} (`{npc_id}`)】",
            f"- 現在の態度: {rel_label}（{rel}）",
        ]
        if personality:
            lines.append(f"- 性格・口調: {personality}")
        lines.append(
            "- この人物になりきって返答・仕草を描写すること。"
            "プレイヤーの技能判定結果に無い秘密を勝手にバラさないこと。"
        )
        if include_secrets:
            revealed = self.get_revealed_secret_ids(npc_id)
            secrets = self.get_secrets(npc_id)
            if revealed:
                lines.append("- 【開示済み・KPは必ずこの内容に触れてよい】")
                for sid in revealed:
                    content = (secrets.get(sid) or {}).get("content", "")
                    if content:
                        lines.append(f"  · {sid}: {content}")
            hidden = [sid for sid in secrets if sid not in revealed]
            if hidden:
                lines.append(
                    "- 【未開示の秘密】以下は判定成功条件を満たすまで絶対に明かさないこと:"
                )
                for sid in hidden:
                    lines.append(f"  · {sid}（内容はシステム内部。条件未達なら匂わせ程度まで）")
        return "\n".join(lines)

    def _eval_reveal_condition(
        self,
        condition: str,
        *,
        success_level: int,
        skill: str,
        relationship: str,
        is_success: bool,
    ) -> bool:
        text = str(condition or "").strip()
        if not text or text.lower() in ("true", "1", "yes"):
            return bool(is_success)
        if text.lower() in ("false", "0", "no"):
            return False
        ctx = {
            "success_level": int(success_level),
            "skill": skill,
            "relationship": relationship,
            "is_success": bool(is_success),
            "SuccessLevel": {
                "FUMBLE": 0,
                "FAILURE": 1,
                "REGULAR": 2,
                "REGULAR_SUCCESS": 2,
                "HARD": 3,
                "HARD_SUCCESS": 3,
                "EXTREME": 4,
                "EXTREME_SUCCESS": 4,
                "CRITICAL": 5,
            },
        }
        try:
            return bool(SafeExpressionEvaluator(ctx).evaluate(text))
        except Exception:
            import re
            m = re.search(r"success_level\s*>=\s*(\d+)", text)
            if m and int(success_level) >= int(m.group(1)):
                skill_ok = True
                if "skill" in text and "in" in text:
                    skill_ok = any(s in text for s in (skill,) if s)
                    # 引用符内に skill 名があるか
                    skill_ok = f"'{skill}'" in text or f'"{skill}"' in text or skill_ok
                return skill_ok
            return bool(is_success)

    def evaluate_secret_reveals(
        self,
        npc_id: str,
        *,
        success_level: int,
        skill: str,
        relationship: str,
        is_success: bool,
    ) -> List[Dict[str, Any]]:
        """条件を満たした秘密を開示し、新規分を返す。"""
        newly = []
        already = set(self.get_revealed_secret_ids(npc_id))
        for sid, secret in self.get_secrets(npc_id).items():
            if sid in already:
                continue
            cond = secret.get("reveal_condition", "success_level >= 2")
            # skill in [...] を評価しやすいよう skill を含む条件をサポート
            if self._eval_reveal_condition(
                cond,
                success_level=success_level,
                skill=skill,
                relationship=relationship,
                is_success=is_success,
            ):
                self.mark_secret_revealed(npc_id, sid)
                newly.append({
                    "id": sid,
                    "content": secret.get("content", ""),
                })
        return newly

    def compute_relationship_delta(
        self,
        skill: str,
        success_level: int,
        *,
        casual: bool = False,
    ) -> int:
        """交渉結果から関係性の変動幅を返す。"""
        if casual:
            return 0
        level = int(success_level)
        if level >= int(SuccessLevel.EXTREME_SUCCESS):
            return 1
        if level >= int(SuccessLevel.HARD_SUCCESS):
            return 1 if skill in ("説得", "魅惑", "言いくるめ") else 0
        if level >= int(SuccessLevel.REGULAR_SUCCESS):
            return 0
        if level == int(SuccessLevel.FUMBLE):
            return -2 if skill == "威圧" else -1
        # 失敗
        if skill == "威圧":
            return -1
        return 0

    def resolve_casual_talk(self, pc_id: str, npc_id: str) -> Dict[str, Any]:
        """雑談：ダイス無し。関係性はほぼ変わらないが対話回数を加算。"""
        npc = self.get_npc(npc_id)
        if not npc:
            return {"ok": False, "log": "【対話】対象のNPCが見つかりません。"}
        social = self.ensure_social_session(npc_id)
        social["dialogue_count"] = int(social.get("dialogue_count") or 0) + 1
        self.char_mgr.save_data()
        name = npc["profile"]["name"]
        pc_name = (self.char_mgr.characters.get(pc_id) or {}).get("profile", {}).get("name", pc_id)
        rel = self.get_relationship(npc_id)
        return {
            "ok": True,
            "casual": True,
            "npc_id": npc_id,
            "npc_name": name,
            "skill": "",
            "success_level": 0,
            "is_success": False,
            "relationship": rel,
            "relationship_label": RELATIONSHIP_LABELS.get(rel, rel),
            "relationship_changed": False,
            "revealed_secrets": [],
            "log": (
                f"【対話】{pc_name} が {name} に話しかけた。"
                f"（態度: {RELATIONSHIP_LABELS.get(rel, rel)}／判定なし）"
            ),
            "kp_instruction": self._build_kp_instruction(
                npc_id, name, casual=True, skill="", revealed=[],
                relationship=rel, is_success=False, success_level=0,
            ),
            "npc_roleplay": self._build_roleplay_payload(npc_id, name, rel, [], True),
        }

    def resolve_negotiation(
        self,
        pc_id: str,
        npc_id: str,
        *,
        skill_name: str,
        dice_engine,
        action_id: str = "negotiate",
    ) -> Dict[str, Any]:
        """交渉技能ロールを実行し、関係性更新・秘密開示を行う。"""
        npc = self.get_npc(npc_id)
        if not npc:
            return {"ok": False, "log": "【交渉】対象のNPCが見つかりません。"}

        skill = resolve_social_skill_name(action_id, skill_name)
        if skill not in SOCIAL_SKILLS and not any(s in skill for s in SOCIAL_SKILLS):
            skill = "説得"

        social = self.ensure_social_session(npc_id)
        social["dialogue_count"] = int(social.get("dialogue_count") or 0) + 1
        old_rel = self.get_relationship(npc_id)
        dice_mod = RELATIONSHIP_DICE_MOD.get(old_rel, RELATIONSHIP_DICE_MOD["neutral"])
        pc_name = (self.char_mgr.characters.get(pc_id) or {}).get("profile", {}).get("name", pc_id)
        npc_name = npc["profile"]["name"]

        pc_value = int(self.char_mgr.get_skill(pc_id, skill) or 0)
        # 心理学: NPC の心理学 or POW/5 対抗相当として、洞察難易度を設定
        if "心理学" in skill:
            npc_psych = int(self.char_mgr.get_skill(npc_id, "心理学") or 0)
            if npc_psych <= 0:
                pow_val = int(self.char_mgr.get_attribute(npc_id, "POW") or 50)
                npc_psych = max(20, pow_val // 2)
            opposed = dice_engine.execute_opposed_skill_roll(
                pc_name, skill, pc_value,
                npc_name, "心理学", npc_psych,
                attacker_bonus=dice_mod["bonus"],
                attacker_penalty=dice_mod["penalty"],
                required_difficulty=dice_mod["difficulty"],
            )
            success_level = int(opposed.get("attacker_level") or 0)
            is_success = opposed.get("winner") == "attacker"
            if is_success:
                success_level = int(opposed.get("success_level") or success_level)
            else:
                success_level = min(success_level, int(SuccessLevel.FAILURE))
            roll_log = opposed.get("log", "")
        else:
            result = dice_engine.execute_skill_roll(
                pc_name, skill, pc_value,
                required_difficulty=dice_mod["difficulty"],
                bonus_dice=dice_mod["bonus"],
                penalty_dice=dice_mod["penalty"],
            )
            if result.get("status") == "error":
                return {
                    "ok": False,
                    "log": result.get("message") or f"【交渉】〈{skill}〉のロールに失敗しました。",
                    "kp_instruction": "対象NPCとの交渉技能が使用できません。別手段を促してください。",
                }
            success_level = int(result.get("success_level") or 0)
            # evaluate_roll が難易度を反映済み。失敗系は is_failure / success_level で判定。
            is_success = (not result.get("is_failure", True)) and is_success_level(success_level)
            if dice_mod["difficulty"] == "hard" and success_level < int(SuccessLevel.HARD_SUCCESS):
                is_success = False
            elif dice_mod["difficulty"] == "extreme" and success_level < int(SuccessLevel.EXTREME_SUCCESS):
                is_success = False
            roll_log = result.get("log", "")

        delta = self.compute_relationship_delta(skill, success_level)
        # 敵対中に威圧成功で無理に屈服→中立までは上がり得るが協力まではこのメソッド外
        if "威圧" in skill and is_success and old_rel == "hostile" and delta >= 0:
            delta = max(delta, 1)
        new_rel = shift_relationship(old_rel, delta) if delta else old_rel
        if new_rel != old_rel:
            self.set_relationship(npc_id, new_rel)
        else:
            self.char_mgr.save_data()

        revealed = []
        if is_success:
            revealed = self.evaluate_secret_reveals(
                npc_id,
                success_level=success_level,
                skill=skill,
                relationship=new_rel,
                is_success=True,
            )

        level_label = {
            0: "ファンブル", 1: "失敗", 2: "レギュラー成功",
            3: "ハード成功", 4: "イクストリーム成功", 5: "クリティカル",
        }.get(success_level, str(success_level))

        log_parts = [
            f"【交渉】{pc_name} → {npc_name}／〈{skill}〉({pc_value})",
            f"態度修正: {RELATIONSHIP_LABELS.get(old_rel, old_rel)}"
            f"（ボーナス{dice_mod['bonus']}／ペナルティ{dice_mod['penalty']}／難易度{dice_mod['difficulty']}）",
            roll_log,
            f"判定結果: {level_label}",
        ]
        if new_rel != old_rel:
            log_parts.append(
                f"【関係性変化】{RELATIONSHIP_LABELS.get(old_rel)} → {RELATIONSHIP_LABELS.get(new_rel)}"
            )
        if revealed:
            for sec in revealed:
                log_parts.append(f"【秘密開示】{sec['id']}: {sec['content']}")
        elif is_success:
            log_parts.append("【情報】相手の警戒がわずかに緩んだが、決定的な秘密は出てこなかった。")
        else:
            log_parts.append("【情報】相手は口を閉ざした。新たな情報は得られなかった。")

        return {
            "ok": True,
            "casual": False,
            "npc_id": npc_id,
            "npc_name": npc_name,
            "skill": skill,
            "success_level": success_level,
            "is_success": is_success,
            "relationship": new_rel,
            "old_relationship": old_rel,
            "relationship_label": RELATIONSHIP_LABELS.get(new_rel, new_rel),
            "relationship_changed": new_rel != old_rel,
            "revealed_secrets": revealed,
            "log": "\n".join(log_parts),
            "kp_instruction": self._build_kp_instruction(
                npc_id, npc_name, casual=False, skill=skill, revealed=revealed,
                relationship=new_rel, is_success=is_success, success_level=success_level,
            ),
            "npc_roleplay": self._build_roleplay_payload(
                npc_id, npc_name, new_rel, revealed, False,
                is_success=is_success, skill=skill,
            ),
        }

    def _build_roleplay_payload(
        self, npc_id, name, relationship, revealed, casual,
        *, is_success=False, skill="",
    ) -> dict:
        return {
            "npc_id": npc_id,
            "name": name,
            "personality": self.get_personality(npc_id),
            "relationship": relationship,
            "relationship_label": RELATIONSHIP_LABELS.get(relationship, relationship),
            "revealed_secrets": revealed,
            "casual": casual,
            "is_success": is_success,
            "skill": skill,
            "prompt_block": self.build_npc_prompt_block(npc_id, include_secrets=True),
        }

    def _build_kp_instruction(
        self, npc_id, name, *, casual, skill, revealed, relationship, is_success, success_level,
    ) -> str:
        rel_label = RELATIONSHIP_LABELS.get(relationship, relationship)
        lines = [
            f"【NPC演技・厳守】あなたは「{name}」として振る舞うこと。",
            f"現在の態度は「{rel_label}」。この態度に忠実な口調・協力度で応答せよ。",
            self.get_personality(npc_id) and f"性格: {self.get_personality(npc_id)}" or "",
        ]
        if casual:
            lines.append("雑談ターンです。情報の核心は incremental に匂わせる程度。判定なしのため決定的な秘密は明かさない。")
        elif is_success:
            lines.append(f"〈{skill}〉成功（成功度{success_level}）。相手は渋々／素直に応じる描写を行う。")
            if revealed:
                lines.append("【システム確定・必ず台詞かナレーションに含める情報】")
                for sec in revealed:
                    lines.append(f"- {sec['content']}")
            else:
                lines.append("成功したが今回の技能では開示条件を満たす秘密は無い。協力的な態度変化や小さな手がかりのみ。")
        else:
            lines.append(f"〈{skill}〉失敗。拒否・誤魔化・警戒・怒りなど、態度「{rel_label}」に沿った拒絶を描写せよ。新しい秘密を漏らすな。")
        lines.append(self.build_npc_prompt_block(npc_id))
        return "\n".join(l for l in lines if l)


def find_npc_id_by_target(char_mgr, target: str) -> Optional[str]:
    """target（ID または名前）から NPC ID を解決する。"""
    if not target:
        return None
    raw = str(target).strip()
    if raw in char_mgr.characters:
        char = char_mgr.characters[raw]
        if char.get("profile", {}).get("is_npc", False):
            return raw
    raw_lower = raw.lower()
    for cid, char in char_mgr.characters.items():
        if not char.get("profile", {}).get("is_npc", False):
            continue
        name = str(char.get("profile", {}).get("name") or "")
        if name == raw or name.lower() == raw_lower:
            return cid
        if raw in name or name in raw:
            return cid
    return None


def format_npc_directory_for_pl(char_mgr, social_mgr: Optional[NPCSocialManager] = None) -> str:
    """PL向け: 対話可能なNPC一覧。"""
    mgr = social_mgr or NPCSocialManager(char_mgr)
    lines = []
    for cid, char in char_mgr.characters.items():
        profile = char.get("profile") or {}
        if not profile.get("is_npc", False):
            continue
        if profile.get("monster"):
            continue
        name = profile.get("name", cid)
        rel = mgr.get_relationship(cid)
        rel_label = RELATIONSHIP_LABELS.get(rel, rel)
        lines.append(f"- {name} (`{cid}`) … 態度: {rel_label}")
    if not lines:
        return ""
    return (
        "\n【対話可能なNPC】\n"
        + "\n".join(lines)
        + "\n"
        + "・雑談: action `talk` / target に NPCのID または名前\n"
        + "・交渉: action `persuade`/`fast_talk`/`intimidate`/`charm`/`psychology`"
        " または skill に〈説得〉〈言いくるめ〉〈威圧〉〈魅惑〉〈心理学〉\n"
    )
