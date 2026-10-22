from mitm_proxy_plugin.campaigns import generate_campaigns, load_manifest
from mitm_proxy_plugin.campaigns.models import (
    Campaign,
    CampaignMode,
    CampaignTarget,
)


def make_minimal_spec():
    return {
        "paths": {
            "/api/items": {
                "get": {
                    "operationId": "getItems",
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "integer"},
                                            "name": {"type": "string"},
                                        },
                                        "required": ["id"],
                                    }
                                }
                            }
                        }
                    },
                }
            }
        }
    }


def test_campaign_round_trip():
    campaign = Campaign(
        campaign_id="c0001_test",
        mode=CampaignMode.SINGLE_MUTANT,
        seed=42,
        spec_sha256="abc123",
        created_at="2026-08-07T00:00:00Z",
        target=CampaignTarget(operation_id="getItems"),
        mutant={"id": "m1", "operator": "MalformedJSON"},
    )

    d = campaign.to_dict()
    restored = Campaign.from_dict(d)
    assert restored.target is not None
    assert restored.mutant is not None
    assert restored.campaign_id == campaign.campaign_id
    assert restored.mode == CampaignMode.SINGLE_MUTANT
    assert restored.target.operation_id == "getItems"
    assert restored.mutant["operator"] == "MalformedJSON"


def test_generate_campaigns(tmp_path):
    spec = make_minimal_spec()

    campaigns = generate_campaigns(
        spec=spec,
        seed=42,
        out_dir=tmp_path,
    )

    assert len(campaigns) > 1
    assert campaigns[0].mode == CampaignMode.BASELINE

    manifest_path = tmp_path / "manifest.jsonl"
    assert manifest_path.exists()

    raw = load_manifest(manifest_path)
    assert len(raw) == len(campaigns)


def test_generate_campaigns_disabled_operators(tmp_path):
    spec = make_minimal_spec()

    campaigns_all = generate_campaigns(
        spec=spec,
        seed=42,
        out_dir=tmp_path / "all",
    )

    campaigns_filtered = generate_campaigns(
        spec=spec,
        seed=42,
        out_dir=tmp_path / "filtered",
        disabled_operators={"MalformedJSON", "InvalidContentType"},
    )

    assert len(campaigns_filtered) < len(campaigns_all)
    for c in campaigns_filtered:
        if c.mutant:
            assert c.mutant["operator"] not in {"MalformedJSON", "InvalidContentType"}
