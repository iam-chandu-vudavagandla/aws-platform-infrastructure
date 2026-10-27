from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SECURITY_WORKFLOW = (
    REPOSITORY_ROOT
    / ".github"
    / "workflows"
    / "security.yaml"
)


def workflow_step(
    workflow: str,
    name: str,
) -> str:
    """Return one named workflow step."""

    marker = f"      - name: {name}\n"

    assert marker in workflow, (
        f"Security workflow is missing step: {name}"
    )

    return workflow.split(
        marker,
        maxsplit=1,
    )[1].split(
        "\n      - name:",
        maxsplit=1,
    )[0]


def test_security_workflow_scans_agent_and_publishes_sbom() -> None:
    workflow = SECURITY_WORKFLOW.read_text(
        encoding="utf-8",
    )

    trivy_action = (
        "uses: aquasecurity/trivy-action@v0.36.0"
    )

    assert workflow.count(trivy_action) == 4
    assert workflow.count("version: v0.76.1") == 4
    build_step = workflow_step(
        workflow,
        "Build reliability-agent security image",
    )

    assert "uses: docker/build-push-action@v7" in build_step
    assert "context: platform-agent" in build_step
    assert "load: true" in build_step
    assert "push: false" in build_step
    assert "tags: platform-agent:security" in build_step

    sbom_step = workflow_step(
        workflow,
        "Generate reliability-agent CycloneDX SBOM",
    )

    assert (
        "uses: aquasecurity/trivy-action@v0.36.0"
        in sbom_step
    )
    assert "scan-type: image" in sbom_step
    assert "image-ref: platform-agent:security" in sbom_step
    assert "scanners: vuln" in sbom_step
    assert "format: cyclonedx" in sbom_step
    assert (
        "output: platform-agent-sbom.cdx.json"
        in sbom_step
    )
    assert 'exit-code: "0"' in sbom_step

    upload_step = workflow_step(
        workflow,
        "Upload reliability-agent SBOM",
    )

    assert "uses: actions/upload-artifact@v4" in upload_step
    assert "name: platform-agent-sbom" in upload_step
    assert (
        "path: platform-agent-sbom.cdx.json"
        in upload_step
    )
    assert "if-no-files-found: error" in upload_step

    scan_step = workflow_step(
        workflow,
        "Scan reliability-agent security image",
    )

    assert (
        "uses: aquasecurity/trivy-action@v0.36.0"
        in scan_step
    )
    assert "scan-type: image" in scan_step
    assert "image-ref: platform-agent:security" in scan_step
    assert "scanners: vuln,secret,misconfig" in scan_step
    assert "severity: HIGH,CRITICAL" in scan_step
    assert "ignore-unfixed: true" in scan_step
    assert "format: table" in scan_step
    assert 'exit-code: "1"' in scan_step
