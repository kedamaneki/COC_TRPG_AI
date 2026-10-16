import os
import unittest
from unittest.mock import patch

import main


class _FailingCompletions:
    def create(self, **_kwargs):
        raise ConnectionError("connection refused")


class _FailingClient:
    def __init__(self):
        self.chat = type("Chat", (), {})()
        self.chat.completions = _FailingCompletions()


class OllamaRoutingTests(unittest.TestCase):
    def setUp(self):
        main.close_llm_client()

    def tearDown(self):
        main.close_llm_client()
        main.configure_llm_metrics()

    def _dual_config(self):
        return {
            "primary_root_url": "http://127.0.0.1:11434",
            "primary_base_url": "http://127.0.0.1:11434/v1",
            "secondary_root_url": "http://secondary.test:11434",
            "secondary_base_url": "http://secondary.test:11434/v1",
            "secondary_explicit": True,
            "secondary_failure_policy": "FAIL_CLOSED",
            "execution_profile": "SCHOOL_DUAL_PC",
        }

    def test_pl_routes_to_primary(self):
        self.assertEqual(main.resolve_ollama_endpoint("player", self._dual_config())["endpoint_class"], "PRIMARY")

    def test_kp_routes_to_primary(self):
        self.assertEqual(main.resolve_ollama_endpoint("keeper", self._dual_config())["endpoint_class"], "PRIMARY")

    def test_judge_routes_to_secondary(self):
        route = main.resolve_ollama_endpoint("judge", self._dual_config())
        self.assertEqual(route["endpoint_class"], "SECONDARY")
        self.assertTrue(route["remote"])

    def test_secondary_missing_falls_back_to_primary_config(self):
        config = self._dual_config()
        config.update({
            "secondary_root_url": config["primary_root_url"],
            "secondary_base_url": config["primary_base_url"],
            "secondary_explicit": False,
        })
        route = main.resolve_ollama_endpoint("JUDGE", config)
        self.assertEqual(route["endpoint_class"], "PRIMARY")
        self.assertTrue(route["config_fallback"])

    def test_formal_mode_secondary_failure_is_fail_closed(self):
        config = {
            **self._dual_config(),
            "api_key": "ollama",
            "pl_model": "qwen2.5:14b",
            "kp_model": "qwen2.5:14b",
            "judge_model": "qwen2.5:14b",
            "timeout": 120.0,
            "max_tokens": 2048,
        }
        with patch.object(main, "get_llm_config", return_value=config), \
             patch.object(main, "get_client", return_value=_FailingClient()), \
             patch.object(main.time, "sleep"):
            with self.assertRaises(main.RemoteOllamaInfrastructureError) as raised:
                main._call_chat_completion(
                    [{"role": "user", "content": "fixture"}],
                    model="qwen2.5:14b", temperature=0.3, max_retries=1,
                    role="JUDGE", purpose="routing_fixture",
                )
        self.assertEqual(raised.exception.error_class, "REMOTE_OLLAMA_CONNECTION_ERROR")

    def test_primary_env_override(self):
        with patch.dict(os.environ, {"PRIMARY_OLLAMA_URL": "http://primary.test:11434"}, clear=False):
            cfg = main.get_llm_config()
        self.assertEqual(cfg["primary_base_url"], "http://primary.test:11434/v1")

    def test_secondary_env_override(self):
        with patch.dict(os.environ, {"SECONDARY_OLLAMA_URL": "http://secondary.test:11434"}, clear=False):
            cfg = main.get_llm_config()
        self.assertEqual(cfg["secondary_base_url"], "http://secondary.test:11434/v1")
        self.assertTrue(cfg["secondary_explicit"])

    def test_legacy_single_url_backward_compatibility(self):
        with patch.dict(os.environ, {
            "PRIMARY_OLLAMA_URL": "",
            "OLLAMA_URL": "http://legacy.test:11434",
        }, clear=False):
            cfg = main.get_llm_config()
        self.assertEqual(cfg["primary_base_url"], "http://legacy.test:11434/v1")
        self.assertEqual(cfg["secondary_base_url"], cfg["primary_base_url"])

    def test_url_validation_rejects_non_http(self):
        with self.assertRaises(ValueError):
            main._normalize_ollama_url("file:///tmp/ollama")


if __name__ == "__main__":
    unittest.main()
