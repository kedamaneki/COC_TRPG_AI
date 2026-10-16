"""
シナリオ条件式（condition / custom_eval）の安全評価器。
許可された AST ノードのみを解釈し、任意コード実行を防ぐ。
"""
import ast
import operator
from typing import Any, Mapping, Optional

_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

_ALLOWED_BOOLOPS = {
    ast.And: all,
    ast.Or: any,
}

_ALLOWED_UNARYOPS = {
    ast.Not: operator.not_,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


class ExpressionEvaluationError(ValueError):
    """条件式のパース・評価に失敗した場合。"""


class _DotAccessMapping:
    """flags.key のようなドットアクセスを辞書に橋渡しする。"""

    def __init__(self, data: Optional[Mapping[str, Any]] = None):
        self._data = dict(data or {})

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._data.get(name)

    def __getitem__(self, key: str):
        return self._data.get(key)

    def get(self, key: str, default=None):
        return self._data.get(key, default)


class GlobalStatesContext:
    """global_states.flags.<name> 形式の式評価用ラッパー。"""

    def __init__(
        self,
        flags: Optional[Mapping[str, Any]] = None,
        counters: Optional[Mapping[str, Any]] = None,
        *,
        phase: str = "",
        location: str = "",
    ):
        self.flags = _DotAccessMapping(flags)
        self.counters = _DotAccessMapping(counters)
        self.phase = phase
        self.location = location


class SafeExpressionEvaluator:
    """制限付き Python 互換条件式評価器。"""

    def __init__(self, context: Optional[Mapping[str, Any]] = None):
        self.context = dict(context or {})

    def evaluate(self, expression: str, *, default: bool = False) -> bool:
        expr = str(expression or "").strip()
        if not expr:
            return default
        try:
            tree = ast.parse(expr, mode="eval")
            result = self._eval_node(tree.body)
            return bool(result)
        except ExpressionEvaluationError:
            raise
        except Exception as exc:
            raise ExpressionEvaluationError(f"条件式評価失敗: {expr!r} ({exc})") from exc

    def evaluate_safe(self, expression: str, *, default: bool = False) -> bool:
        try:
            return self.evaluate(expression, default=default)
        except ExpressionEvaluationError as exc:
            print(f"[ExpressionEvaluator] {exc}")
            return default

    def _eval_node(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return self._resolve_name(node.id)
        if isinstance(node, ast.Attribute):
            base = self._eval_node(node.value)
            if base is None:
                return None
            if isinstance(base, _DotAccessMapping):
                return base.get(node.attr)
            if isinstance(base, Mapping):
                return base.get(node.attr)
            return getattr(base, node.attr, None)
        if isinstance(node, ast.Subscript):
            base = self._eval_node(node.value)
            key = self._eval_node(node.slice)
            if isinstance(base, Mapping):
                return base.get(key)
            if isinstance(base, (list, tuple)):
                try:
                    return base[key]
                except (IndexError, TypeError):
                    return None
            return None
        if isinstance(node, ast.Compare):
            left = self._eval_node(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval_node(comparator)
                func = _ALLOWED_BINOPS.get(type(op))
                if func is None:
                    raise ExpressionEvaluationError(f"未対応の比較演算子: {type(op).__name__}")
                if not func(left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.BoolOp):
            func = _ALLOWED_BOOLOPS.get(type(node.op))
            if func is None:
                raise ExpressionEvaluationError(f"未対応の論理演算子: {type(node.op).__name__}")
            values = [bool(self._eval_node(v)) for v in node.values]
            return func(values)
        if isinstance(node, ast.UnaryOp):
            func = _ALLOWED_UNARYOPS.get(type(node.op))
            if func is None:
                raise ExpressionEvaluationError(f"未対応の単項演算子: {type(node.op).__name__}")
            return func(self._eval_node(node.operand))
        if isinstance(node, ast.BinOp):
            func = _ALLOWED_BINOPS.get(type(node.op))
            if func is None:
                raise ExpressionEvaluationError(f"未対応の二項演算子: {type(node.op).__name__}")
            return func(self._eval_node(node.left), self._eval_node(node.right))
        if isinstance(node, ast.List):
            return [self._eval_node(elt) for elt in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(self._eval_node(elt) for elt in node.elts)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "len":
                if len(node.args) != 1 or node.keywords:
                    raise ExpressionEvaluationError("len() は引数1つのみ許可")
                return len(self._eval_node(node.args[0]) or [])
            raise ExpressionEvaluationError("関数呼び出しは len() のみ許可")
        raise ExpressionEvaluationError(f"未対応の式ノード: {type(node).__name__}")

    def _resolve_name(self, name: str) -> Any:
        aliases = {
            "true": True,
            "false": False,
            "null": None,
            "True": True,
            "False": False,
            "None": None,
        }
        if name in aliases:
            return aliases[name]
        if name in self.context:
            return self.context[name]
        raise ExpressionEvaluationError(f"未定義の識別子: {name}")


def build_scenario_eval_context(
    *,
    action_id: str = "",
    target: str = "",
    success_level: int = 0,
    location: str = "",
    current_phase: str = "",
    flags: Optional[Mapping[str, Any]] = None,
    counters: Optional[Mapping[str, Any]] = None,
    investigated_targets=None,
    object_data: Optional[Mapping[str, Any]] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict:
    """ScenarioManager 向けの評価コンテキストを組み立てる。"""
    flag_map = dict(flags or {})
    ctx = {
        "action_id": action_id,
        "target": target,
        "success_level": success_level,
        "location": location,
        "current_phase": current_phase,
        "turn_counter": (counters or {}).get("turn_counter", flag_map.get("turn_counter", 0)),
        "flags": _DotAccessMapping(flag_map),
        "global_states": GlobalStatesContext(
            flag_map,
            counters,
            phase=current_phase,
            location=location,
        ),
        "investigated_targets": list(investigated_targets or []),
        "object": _DotAccessMapping(object_data or {}),
        "target_str": (object_data or {}).get("STR", 0),
        "target_difficulty": (object_data or {}).get("difficulty"),
        "true": True,
        "false": False,
        "null": None,
    }
    if extra:
        ctx.update(extra)
    return ctx
