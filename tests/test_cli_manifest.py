import json

import pytest

from mitm_proxy_plugin.campaigns.models import Campaign, CampaignMode
from mitm_proxy_plugin.cli.generate_manifest import (
    generate_for_spec,
    print_summary,
    scan_restberus_dir,
)


@pytest.fixture
def sample_spec_path(tmp_path):
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Users Service", "version": "1.0"},
        "paths": {
            "/users": {
                "get": {
                    "operationId": "getUsers",
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["id"],
                                        "properties": {
                                            "id": {"type": "integer"},
                                            "role": {
                                                "type": "string",
                                                "enum": ["ADMIN", "USER"],
                                            },
                                        },
                                    }
                                }
                            }
                        }
                    },
                }
            }
        },
    }
    path = tmp_path / "users_openapi.json"
    path.write_text(json.dumps(spec))
    return path


def test_generate_for_spec_basic(sample_spec_path, tmp_path):
    out_dir = tmp_path / "out"
    count = generate_for_spec(
        spec_path=sample_spec_path,
        out_dir=out_dir,
        seed=42,
    )

    assert count > 1
    manifest_path = out_dir / "manifest.jsonl"
    assert manifest_path.exists()

    with manifest_path.open() as f:
        lines = [json.loads(line) for line in f if line.strip()]

    assert len(lines) == count
    # First campaign must be baseline
    assert lines[0]["mode"] == CampaignMode.BASELINE.value


def test_generate_for_spec_whitelist(sample_spec_path, tmp_path):
    out_dir = tmp_path / "out_whitelist"
    count = generate_for_spec(
        spec_path=sample_spec_path,
        out_dir=out_dir,
        seed=42,
        enabled_operators={"Simulate502", "Simulate503"},
    )

    assert count == 3
    manifest_path = out_dir / "manifest.jsonl"
    with manifest_path.open() as f:
        lines = [json.loads(line) for line in f if line.strip()]

    # Baseline + 2 mutants
    assert len(lines) == 3

    for line in lines[1:]:
        assert line["mutant"]["operator"] in {"Simulate502", "Simulate503"}


def test_generate_for_spec_blacklist(sample_spec_path, tmp_path):
    out_dir_all = tmp_path / "out_all"
    count_all = generate_for_spec(
        spec_path=sample_spec_path,
        out_dir=out_dir_all,
        seed=42,
    )

    out_dir_filtered = tmp_path / "out_blacklisted"
    count_filtered = generate_for_spec(
        spec_path=sample_spec_path,
        out_dir=out_dir_filtered,
        seed=42,
        disabled_operators={"Simulate502", "Simulate503"},
    )

    assert count_filtered == count_all - 2


def test_generate_for_spec_max_per_operation(sample_spec_path, tmp_path):
    out_dir = tmp_path / "out_limited"
    count = generate_for_spec(
        spec_path=sample_spec_path,
        out_dir=out_dir,
        seed=42,
        max_per_operation=2,
    )

    # 1 baseline + 2 mutants
    assert count == 3


def test_generate_for_spec_dry_run(sample_spec_path, tmp_path):
    out_dir = tmp_path / "out_dry"
    count = generate_for_spec(
        spec_path=sample_spec_path,
        out_dir=out_dir,
        seed=42,
        dry_run=True,
    )

    assert count > 0
    # Dry run must not create manifest file in out_dir
    assert not (out_dir / "manifest.jsonl").exists()


def test_generate_for_spec_existing_without_force(sample_spec_path, tmp_path):
    out_dir = tmp_path / "out_exists"
    # First run
    c1 = generate_for_spec(spec_path=sample_spec_path, out_dir=out_dir, seed=42)
    assert c1 > 0

    # Second run without force should skip (return 0)
    c2 = generate_for_spec(
        spec_path=sample_spec_path, out_dir=out_dir, seed=42, force=False
    )
    assert c2 == 0

    # Third run with force should regenerate
    c3 = generate_for_spec(
        spec_path=sample_spec_path, out_dir=out_dir, seed=42, force=True
    )
    assert c3 == c1


def test_generate_for_spec_nonexistent_or_invalid(tmp_path):
    nonexistent = tmp_path / "no_such_file.json"
    count_none = generate_for_spec(
        spec_path=nonexistent, out_dir=tmp_path / "out", seed=42
    )
    assert count_none == 0

    invalid = tmp_path / "invalid.json"
    invalid.write_text("not json content {")
    count_invalid = generate_for_spec(
        spec_path=invalid, out_dir=tmp_path / "out", seed=42
    )
    assert count_invalid == 0


def test_print_summary():
    campaigns = [
        Campaign(
            campaign_id="c0",
            mode=CampaignMode.BASELINE,
            seed=42,
            spec_sha256="abc",
            created_at="",
        ),
        Campaign(
            campaign_id="c1",
            mode=CampaignMode.SINGLE_MUTANT,
            seed=42,
            spec_sha256="abc",
            created_at="",
            mutant={
                "operator": "Simulate502",
                "taxonomy_path": "Service Deployment Fault > Wrong Configuration",
            },
        ),
    ]
    # Should not raise any exceptions
    print_summary(campaigns, "users-service")


def test_scan_restberus_dir(sample_spec_path, tmp_path):
    # Mock RESTberus root structure
    restberus_dir = tmp_path / "RESTberus"
    specs_dir = restberus_dir / "specs" / "test-system"
    specs_dir.mkdir(parents=True, exist_ok=True)

    spec_file = specs_dir / "test-service.json"
    spec_file.write_text(sample_spec_path.read_text())

    # Create dummy .dict.json which should be ignored
    dict_file = specs_dir / "test-service.dict.json"
    dict_file.write_text("{}")

    scan_restberus_dir(restberus_dir=restberus_dir, seed=42)

    manifest_file = (
        restberus_dir / "manifests" / "test-system" / "test-service" / "manifest.jsonl"
    )
    assert manifest_file.exists()
