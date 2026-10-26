"""Regression checks for the release workflow's PyPI publication policy."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = (ROOT / ".github" / "workflows" / "release.yml").read_text(
    encoding="utf-8"
)


def test_pypi_publishing_is_automatic_only_for_main_push_or_manual_opt_in() -> None:
    """Main-branch pushes publish versions; tag pushes alone do not."""
    publish_job = RELEASE_WORKFLOW.split("  publish-pypi:", maxsplit=1)[1]

    assert "github.event_name == 'push'" in publish_job
    assert "github.ref == 'refs/heads/main'" in publish_job
    assert "github.event_name == 'workflow_dispatch'" in publish_job
    assert "inputs.publish_pypi == true" in publish_job


def test_pypi_opt_in_defaults_to_false() -> None:
    """A manual workflow run must not publish unless explicitly opted in."""
    input_section = RELEASE_WORKFLOW.split("      publish_pypi:", maxsplit=1)[1].split(
        "\n\npermissions:", maxsplit=1
    )[0]

    assert "default: false" in input_section
    assert "type: boolean" in input_section
