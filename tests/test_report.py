import json
from html.parser import HTMLParser

import pytest
from pydantic import ValidationError

from histcmp.checks import CheckSummary, Status
from histcmp.compare import Comparison, ComparisonItem
from histcmp.config import Config, ReportConfig
from histcmp.report import make_report, check_metadata


class ReportParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.metadata = ""
        self.in_metadata = False
        self.images = []
        self.templates = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("id") == "report-data":
            self.in_metadata = True
        if tag == "img":
            self.images.append(attrs)
        if tag == "template":
            self.templates.append(attrs["id"])

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_metadata = False

    def handle_data(self, data):
        if self.in_metadata:
            self.metadata += data


def test_report_tags_and_escaping(tmp_path):
    keys = ["tracking/ckf_eta", "tracking/other", "efficiency", "TRACKING/other",
            '</script><img src=x onerror="alert(1)">']
    items = []
    for key in keys:
        item = ComparisonItem(key, None, None)
        item._generic_plots = [tmp_path / "image #1.png"]
        item.checks = [CheckSummary(
            "Check <name>", Status.SUCCESS, True, True, False, "<value>\n---\nrest"
        )]
        items.append(item)
    output = tmp_path / "report.html"
    config = ReportConfig(tags={
        "Tracking": ["tracking/*", "*ckf*"],
        "Efficiency": ["eff*", "*eta"],
        "Empty": [],
    })
    make_report(Comparison("a", "b", items=items), output, report_config=config)
    html = output.read_text()
    parsed = ReportParser(html)
    metadata = json.loads(parsed.metadata)
    assert [item["title"] for item in metadata["items"]] == keys
    assert [item["tags"] for item in metadata["items"]] == [
        ["Tracking", "Efficiency"], ["Tracking"], ["Efficiency"], [], [],
    ]
    assert metadata["tags"] == ["Tracking", "Efficiency", "Empty"]
    assert parsed.templates == [f"template-plot-{i}" for i in range(len(keys))]
    assert len(parsed.images) == len(keys)
    assert all("src" not in image for image in parsed.images)
    assert all(image["data-src"] == "image%20%231.png" for image in parsed.images)
    assert keys[-1] not in html
    assert "&lt;value&gt;<br><hr><br>rest" in html
    assert "Check &lt;name&gt;" in html


def test_empty_report(tmp_path):
    output = tmp_path / "empty.html"
    make_report(Comparison("a", "b"), output)
    parsed = ReportParser(output.read_text())
    assert json.loads(parsed.metadata) == {"items": [], "tags": []}
    assert parsed.templates == []
    assert parsed.images == []


def test_report_config_compatibility():
    assert Config(checks={}).report.tags == {}
    legacy = ReportConfig(categories={"Tracking": ["*track*"]})
    assert legacy.tags == {"Tracking": ["*track*"]}
    assert legacy.model_dump() == {"tags": {"Tracking": ["*track*"]}}
    with pytest.raises(ValidationError):
        ReportConfig(tags={"Tracking": "*track*"})


def test_check_rank_json_and_disabled_checks():
    check = CheckSummary("IntegralTest", Status.FAILURE, True, False, False, "Infinite pull", sort_value=float("inf"))
    metadata = check_metadata(check)
    assert metadata["sortValue"] > 1e300
    json.dumps(metadata, allow_nan=False)
    check.sort_value = float("nan")
    assert check_metadata(check)["sortValue"] is None
    check.sort_value = 3
    check.is_disabled = True
    assert check_metadata(check)["sortValue"] is None


def test_added_and_missing_summary(tmp_path):
    output = tmp_path / "summary.html"
    comparison = Comparison("monitored", "reference", a_only={("new<plot>", "TH1F")}, b_only={("old<plot>", "TH2F")})
    make_report(comparison, output)
    html = output.read_text()
    assert "1 added" in html and "1 missing" in html
    assert "new&lt;plot&gt;" in html and "old&lt;plot&gt;" in html
    assert "new<plot>" not in html
