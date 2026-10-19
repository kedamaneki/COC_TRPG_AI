import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_tool(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class V23PresentationIntegrationTests(unittest.TestCase):
    def test_registry_resolves_role_specific_names(self):
        registry = json.loads((ROOT / "video/config/character_registry.json").read_text(encoding="utf-8-sig"))["speaker_assignments"]
        self.assertEqual(registry["pl_01"]["pl_display_name"], "霊夢")
        self.assertEqual(registry["pc_01"]["pc_display_name"], "マクガフィン刑事")
        self.assertEqual(registry["pl_02"]["pl_display_name"], "魔理沙")
        self.assertEqual(registry["pc_02"]["pc_display_name"], "エレノア教授")
        self.assertEqual(registry["kp"]["kp_display_name"], "KP")
        self.assertIsNone(registry["system"]["system_display_name"])

    def test_optional_object_visual_is_nonblocking_and_generic_background_is_weak(self):
        tool = load_tool("asset_analyzer_v23", ROOT / "tools/analyze_video_asset_requirements.py")
        with tempfile.TemporaryDirectory() as tmp:
            background = Path(tmp) / "background.png"
            background.write_bytes(b"fixture")
            result = tool.analyze_requirements([
                {"requirement_id": "background", "asset_type": "BACKGROUND", "location_id": "basement", "priority": "REQUIRED"},
                {"requirement_id": "object", "asset_type": "OPTIONAL_OBJECT_VISUAL", "semantic": "planks", "priority": "OPTIONAL"},
            ], [{"asset_id": "generic", "asset_type": "BACKGROUND", "path": str(background),
                 "generic_environment": True, "approval_status": "APPROVED_FOR_PREVIEW"}])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["critical_asset_missing"], 0)
        self.assertEqual(result["requirements"][0]["match_quality"], "WEAK_MATCH")
        self.assertFalse(result["requirements"][1]["blocking"])

    def test_asset_scan_refreshes_without_false_missing_for_assets_outside_scan_root(self):
        tool = load_tool("asset_scan_v23", ROOT / "tools/scan_video_assets.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scan_root = root / "video/assets/user_inputs"
            scan_root.mkdir(parents=True)
            registry = root / "video/config/asset_registry.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(json.dumps({"assets": [{"asset_id": "elsewhere", "path": "assets/yukkuri/a.png",
                                                         "approval_status": "APPROVED_FOR_PREVIEW"}]}), encoding="utf-8")
            report = tool.scan_assets(scan_root, registry)
        self.assertTrue(report["scan_executed"])
        self.assertTrue(report["registry_refreshed"])
        self.assertEqual(report["counts"]["MISSING_ASSET"], 0)


if __name__ == "__main__":
    unittest.main()
