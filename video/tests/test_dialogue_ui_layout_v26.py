from video_agent.presentation.dialogue_ui import (
    DEFAULT_DIALOGUE_FONT_SIZE,
    DEFAULT_NAME_FONT_SIZE,
    audit_dialogue_ui,
    layout_for_canvas,
)


def _clip(fixture_id: str, speaker_id: str, speaker_name: str, subtitle_text: str,
          icon: str | None = "portrait") -> dict:
    return {
        "fixture_id": fixture_id,
        "speaker_id": speaker_id,
        "speaker_name": speaker_name,
        "subtitle_text": subtitle_text,
        "speaker_icon_asset_id": icon,
        "presentation_mode": "SUBTITLE_ONLY" if speaker_id == "system" else "VOICED",
    }


def test_fixture_dialogue_ui_layout_001() -> None:
    layout = layout_for_canvas()
    fixtures = [
        _clip("pl1_one_line", "pl_01", "霊夢", "いい出目ね。"),
        _clip("pc1_long_name", "pc_01", "マクガフィン刑事", "板を調べます。"),
        _clip("pl2_one_line", "pl_02", "魔理沙", "次はどうする？"),
        _clip("pc2_long_name", "pc_02", "エレノア教授", "力を込めて板を押します。"),
        _clip("kp_one_line", "kp", "KP", "では、筋力で判定してください。目標値は55です。"),
        _clip("two_lines", "kp", "KP", "古い板は湿気を吸って軋み、力を込めると大きくたわみます。しかし、まだ完全には外れていません。"),
        _clip("maximum_length", "pc_01", "マクガフィン刑事", "地下室をいったん離れて屋敷内を調べ直したあと、再び戻ってきて古びた板へ慎重に力を込めます。"),
        _clip("system", "system", "", "筋力　目標55／出目24　ハード成功", None),
    ]
    report = audit_dialogue_ui(fixtures, layout)
    assert report["status"] == "PASS", report
    assert fixtures[-1]["speaker_icon_asset_id"] is None
    assert fixtures[-1]["speaker_name"] == ""
    assert max(item["dialogue_ui"]["line_count"] for item in fixtures) <= 2
    assert all(not item["dialogue_ui"]["overflow"] for item in fixtures)
    assert DEFAULT_DIALOGUE_FONT_SIZE == 62
    assert DEFAULT_NAME_FONT_SIZE == 62
    assert {item["dialogue_ui"]["name_font_size"] for item in fixtures[:-1]} == {62}


def test_layout_scales_with_canvas_ratio() -> None:
    full = layout_for_canvas(1920, 1080)
    half = layout_for_canvas(960, 540)
    assert half.name_plate.width == full.name_plate.width // 2
    assert half.speaker_icon.height == round(full.speaker_icon.height / 2)
    assert not full.speaker_icon.overlaps(full.name_plate)
    assert not full.speaker_icon.overlaps(full.text_safe_area)


def test_v7_is_the_default_dialogue_layout() -> None:
    layout = layout_for_canvas()
    assert (layout.dialogue_frame.x, layout.dialogue_frame.y,
            layout.dialogue_frame.width, layout.dialogue_frame.height) == (0, 660, 1920, 420)
    assert (layout.name_plate.x, layout.name_plate.y,
            layout.name_plate.width, layout.name_plate.height) == (0, 660, 640, 68)
    assert layout.name_plate.center == (320, 694)
    assert (layout.text_safe_area.x, layout.text_safe_area.y,
            layout.text_safe_area.width, layout.text_safe_area.height) == (287, 766, 1561, 278)
    assert layout.speaker_icon_scale == 1.15
