from datetime import date

from cvforge.track.stages import add_stage, complete_stage, load_stages


def test_stage_roundtrip(tmp_path):
    assert load_stages(tmp_path / "none") == []
    app = tmp_path / "app"
    add_stage(app, "Phone screen", "interview", date(2026, 6, 1))
    add_stage(app, "Take-home", "test", None)
    complete_stage(app, "phone screen")
    stages = load_stages(app)
    assert [(s.name, s.kind, s.due, s.done) for s in stages] == [
        ("Phone screen", "interview", date(2026, 6, 1), True),
        ("Take-home", "test", None, False),
    ]
