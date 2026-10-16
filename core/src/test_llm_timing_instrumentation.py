import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main
import run_investigation_evaluation as runner


class _FakeResponse:
    def __init__(self):
        message = type("Message", (), {"content": '{"ok": true}'})()
        self.choices = [type("Choice", (), {"message": message, "finish_reason": "stop"})()]

    def model_dump(self):
        return {
            "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
        }


class _FakeCompletions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return _FakeResponse()


class _FakeClient:
    def __init__(self):
        self.chat = type("Chat", (), {})()
        self.chat.completions = _FakeCompletions()


class LlmTimingInstrumentationTests(unittest.TestCase):
    def test_metrics_are_recorded_without_changing_inference_arguments(self):
        fake = _FakeClient()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "llm_call_metrics.jsonl"
            main.configure_llm_metrics(
                path,
                context_provider=lambda: {"cycle": 7, "turn": 21},
                reset=True,
            )
            with patch.object(main, "get_client", return_value=fake), patch.object(main.time, "sleep"):
                result = main._call_chat_completion(
                    [{"role": "user", "content": "unchanged"}],
                    model="qwen2.5:14b",
                    temperature=0.7,
                    max_retries=1,
                    json_mode=True,
                    role="PL",
                    purpose="action_selection",
                )
            self.assertEqual(result, '{"ok": true}')
            self.assertEqual(fake.chat.completions.kwargs, {
                "model": "qwen2.5:14b",
                "messages": [{"role": "user", "content": "unchanged"}],
                "temperature": 0.7,
                "response_format": {"type": "json_object"},
                "max_tokens": main.get_llm_config()["max_tokens"],
            })
            row = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual((row["cycle"], row["turn"]), (7, 21))
            self.assertEqual((row["role"], row["purpose"]), ("PL", "action_selection"))
            self.assertEqual((row["prompt_eval_count"], row["eval_count"]), (120, 30))
            self.assertEqual(row["status"], "SUCCESS")
            self.assertEqual(row["total_duration_source"], "client_wall_clock")
        main.configure_llm_metrics()

    def test_performance_summary_groups_roles_and_computes_per_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            rows = [
                {"role": "PL", "status": "SUCCESS", "prompt_eval_count": 100,
                 "eval_count": 20, "wall_duration_seconds": 10.0, "retry_count": 0},
                {"role": "KP", "status": "SUCCESS", "prompt_eval_count": 200,
                 "eval_count": 40, "wall_duration_seconds": 20.0, "retry_count": 1},
            ]
            (output / "llm_call_metrics.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8",
            )
            summary = runner._write_llm_performance_summary(output, turns=2)
            self.assertEqual(summary["roles"]["PL"]["total_calls"], 1)
            self.assertEqual(summary["roles"]["KP"]["retry_count"], 1)
            self.assertEqual(summary["per_turn"]["llm_calls"], 1.0)
            self.assertEqual(summary["per_turn"]["prompt_tokens"], 150.0)
            self.assertEqual(summary["per_turn"]["completion_tokens"], 30.0)
            self.assertEqual(summary["per_turn"]["llm_seconds"], 15.0)


if __name__ == "__main__":
    unittest.main()
