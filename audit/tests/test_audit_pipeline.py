from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_DIR = REPO_ROOT / "audit"
if str(AUDIT_DIR) not in sys.path:
    sys.path.insert(0, str(AUDIT_DIR))

import audit_pipeline as ap  # noqa: E402


REPORT_HEADINGS = [
    "## Executive summary",
    "## Scorecard",
    "## Code quality",
    "## Test coverage",
    "## Security issues",
    "## Documentation",
    "## CI/CD",
    "## Dependency health",
    "## License compliance",
    "## Recommended next steps",
]


@pytest.fixture(scope="module")
def audited_repo(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, dict[str, object]]:
    temp_dir = tmp_path_factory.mktemp("repo-audit")
    report_path = temp_dir / "audit-report.md"
    json_path = temp_dir / "audit-report.json"
    exit_code = ap.main(["--repo", str(REPO_ROOT), "--output", str(report_path), "--json-output", str(json_path)])
    assert exit_code == 0
    metrics = json.loads(json_path.read_text(encoding="utf-8"))
    return report_path, json_path, metrics


def test_audit_pipeline_runs_on_test_repo(audited_repo: tuple[Path, Path, dict[str, object]]) -> None:
    report_path, json_path, metrics = audited_repo

    assert report_path.exists()
    assert json_path.exists()
    assert metrics["repo"]["source_kind"] == "path"
    assert metrics["repo"]["file_count"] > 0
    assert metrics["checks"]["code_quality"]["metrics"]["python_files"] > 0
    assert metrics["checks"]["test_coverage"]["metrics"]["test_files"] > 0
    assert metrics["summary"]["check_count"] == 7


def test_report_contains_all_required_sections(audited_repo: tuple[Path, Path, dict[str, object]]) -> None:
    report_path, _, _ = audited_repo
    report = report_path.read_text(encoding="utf-8")
    assert report.startswith("# AI-SDLC Repo Audit Report")
    for heading in REPORT_HEADINGS:
        assert heading in report


def test_json_metrics_are_valid(audited_repo: tuple[Path, Path, dict[str, object]]) -> None:
    _, json_path, metrics = audited_repo

    assert isinstance(metrics, dict)
    assert {"repo", "summary", "checks"}.issubset(metrics)
    assert isinstance(metrics["summary"]["overall_score"], (int, float))
    assert isinstance(metrics["checks"], dict)
    assert json.loads(json_path.read_text(encoding="utf-8")) == metrics


def test_invalid_repo_url_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        ap.main(["--repo", "not-a-url", "--output", str(tmp_path / "bad-report.md")])

    assert exc.value.code != 0
