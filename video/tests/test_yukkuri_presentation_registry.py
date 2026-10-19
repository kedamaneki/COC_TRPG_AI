import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from video_agent.registry import PresentationRegistry, RegistryError
from video_agent.rendering.pipeline import M1Pipeline


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def load_scanner():
    path = REPO / "tools" / "scan_video_assets.py"
    spec = importlib.util.spec_from_file_location("scan_video_assets", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class YukkuriPresentationRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = PresentationRegistry(ROOT / "config")

    def test_sixteen_characters_and_common_exact_settings(self):
        self.assertEqual(len(self.registry.characters), 16)
        common = self.registry.subtitle_document["common_style"]
        self.assertEqual((common["font_family"], common["font_size_px"]), ("たぬき油性マジック", 100.0))
        self.assertEqual(common["position"]["y_px"], 530.0)
        self.assertEqual(common["anchor"], "CENTER_BOTTOM")
        self.assertEqual(common["word_wrap"], "NO_WRAP")
        self.assertEqual(common["max_width_px"], 1920.0)
        self.assertEqual((common["outline"]["width_px"], common["outline"]["quality"]), (5.0, 64.0))

    def test_exact_runtime_colors(self):
        styles = {item["character_id"]: item for item in self.registry.subtitle_document["styles"]}
        self.assertEqual((styles["reimu"]["text_color_hex"], styles["reimu"]["decoration_color_hex"]),
                         ("#FF0000", "#FFFFFF"))
        self.assertEqual((styles["marisa"]["text_color_hex"], styles["marisa"]["decoration_color_hex"],
                          styles["marisa"]["outline_color_hex"]), ("#FFFF00", "#000000", "#FFFFFF"))
        self.assertEqual(styles["sakuya"]["decoration_color_hex"], "#464646")
        self.assertTrue(all(item["legacy_exact"] for item in styles.values()))

    def test_active_assignments_resolve_only_through_registry(self):
        reimu = self.registry.resolve_speaker("pc_01")
        marisa = self.registry.resolve_speaker("pl_02")
        sakuya = self.registry.resolve_speaker("kp")
        system = self.registry.resolve_speaker("system")
        self.assertEqual(reimu["character_id"], "reimu")
        self.assertEqual(marisa["character_id"], "marisa")
        self.assertEqual(sakuya["character_id"], "sakuya")
        self.assertEqual(sakuya["voice_profile_id"], "sakuya_tune_110_v1")
        self.assertIsNone(system["character_id"])
        self.assertIsNone(system["voice_profile_id"])
        self.assertIsNone(system["portrait_asset_id"])

    def test_future_candidates_never_auto_use(self):
        active = {"reimu", "marisa", "sakuya"}
        for character_id, item in self.registry.characters.items():
            if character_id not in active:
                self.assertEqual(item["assignment_status"], "FUTURE_CANDIDATE")
                self.assertFalse(item["auto_use"])

    def test_pipeline_uses_registry_documents(self):
        pipeline = M1Pipeline(ROOT, ROOT / "projects" / "m1_synthetic")
        self.assertIsInstance(pipeline.presentation_registry, PresentationRegistry)
        self.assertEqual(pipeline.characters["pc_01"]["subtitle_profile_id"], "subtitle_reimu")
        self.assertEqual(pipeline.characters["kp"]["voice_profile_id"], "m1_vv_kp")

    def test_missing_asset_is_fail_closed(self):
        with self.assertRaisesRegex(RegistryError, "ASSET_MISSING"):
            self.registry.resolve_asset("does_not_exist")

    def test_new_changed_and_duplicate_assets_are_not_approved(self):
        scanner = load_scanner()
        temp_root = ROOT / ".test-tmp"
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as directory:
            root = Path(directory)
            scan = root / "inputs"; scan.mkdir()
            known = scan / "known.png"; known.write_bytes(b"old")
            registry_path = root / "asset_registry.json"
            digest = scanner.sha256_file(known)
            registry_path.write_text(json.dumps({"schema_version":"1.0","assets":[{
                "asset_id":"known","path":"known.png","sha256":digest,"approval_status":"APPROVED"
            }]}), encoding="utf-8")
            report = scanner.scan_assets(scan, registry_path)
            self.assertEqual(report["counts"]["UNCHANGED"], 1)
            (scan / "new.wav").write_bytes(b"new")
            (scan / "copy.wav").write_bytes(b"new")
            known.write_bytes(b"changed")
            report = scanner.scan_assets(scan, registry_path)
            statuses = {item["path"]: item["scan_status"] for item in report["findings"]}
            self.assertEqual(statuses["known.png"], "CHANGED_HASH")
            self.assertIn(statuses["new.wav"], {"NEW_ASSET", "DUPLICATE_CONTENT"})
            self.assertEqual(sum(item["scan_status"] == "DUPLICATE_CONTENT" for item in report["findings"]), 1)
            registered = json.loads(registry_path.read_text(encoding="utf-8"))["assets"]
            additions = [item for item in registered if item["asset_id"] != "known"]
            self.assertTrue(additions)
            self.assertTrue(all(item["approval_status"] == "NOT_APPROVED" and not item["auto_use"]
                                for item in additions))
            self.assertTrue(all(item["license_status"] == "LICENSE_REVIEW_REQUIRED" for item in additions))


if __name__ == "__main__":
    unittest.main()
