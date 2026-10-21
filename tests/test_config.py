import pytest

from histcmp.config import Config


@pytest.mark.parametrize("extension", ["yaml", "yml", "conf", "toml", "TOML"])
def test_config_formats(tmp_path, extension):
    path = tmp_path / f"settings.{extension}"
    path.write_text(
        '[checks."tracking/*".Chi2Test]\nthreshold = 0.01\n'
        '[plots]\nrenderer_3d = "scatter"\ncomparison = "residual"\n'
        '[report.tags]\n"Tracking plots" = ["tracking/*", "*ckf*"]\n'
        if extension.lower() == "toml" else
        'checks:\n  "tracking/*":\n    Chi2Test:\n      threshold: 0.01\n'
        'plots:\n  renderer_3d: scatter\n  comparison: residual\n'
        'report:\n  tags:\n    Tracking plots: ["tracking/*", "*ckf*"]\n',
        encoding="utf-8",
    )
    assert Config.from_file(path) == Config(
        checks={"tracking/*": {"Chi2Test": {"threshold": 0.01}}},
        plots={"renderer_3d": "scatter", "comparison": "residual"},
        report={"tags": {"Tracking plots": ["tracking/*", "*ckf*"]}},
    )


@pytest.mark.parametrize("extension,content", [
    ("toml", "[broken"), ("yaml", "checks: ["),
    ("toml", 'checks = "invalid"'), ("yaml", "checks: invalid"),
    ("toml", ""), ("yaml", ""),
])
def test_invalid_config_reports_filename(tmp_path, extension, content):
    path = tmp_path / f"invalid.{extension}"
    path.write_text(content)
    with pytest.raises(ValueError, match=f"Cannot load configuration {path}"):
        Config.from_file(path)
