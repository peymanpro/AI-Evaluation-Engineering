"""Regression checks for the release workflow's PyPI publication policy."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = (ROOT / ".github" / "workflows" / "release.yml").read_text(
    encoding="utf-8"
)


def test_pypi_publishing_is_disabled_for_push_and_tag_events() -> None:
    """Only an explicit workflow-dispatch opt-in may upload to PyPI."""
    publish_job = RELEASE_WORKFLOW.split("  publish-pypi:", maxsplit=1)[1]

    assert "github.event_name == 'workflow_dispatch'" in publish_job
    assert "inputs.publish_pypi == true" in publish_job
    assert "github.event_name == 'push'" not in publish_job
    assert "github.ref == 'refs/heads/main'" not in publish_job


def test_pypi_opt_in_defaults_to_false() -> None:
    """Running the release workflow manually must not publish unless opted in."""
    input_section = RELEASE_WORKFLOW.split("      publish_pypi:", maxsplit=1)[1].split(
        "\n\npermissions:", maxsplit=1
    )[0]

    assert "default: false" in input_section
    assert "type: boolean" in input_section
