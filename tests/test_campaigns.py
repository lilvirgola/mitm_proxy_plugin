from mitm_proxy_plugin.campaigns.models import (
    Campaign,
    CampaignMode,
    CampaignTarget,
)
from mitm_proxy_plugin.campaigns.generator import generate_campaigns
from mitm_proxy_plugin.campaigns.claimer import claim_next_campaign, load_manifest


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


def test_claim_sequential(tmp_path):
    spec = make_minimal_spec()

    generate_campaigns(spec=spec, seed=42, out_dir=tmp_path / "apis" / "test-api" / "campaigns")

    c1 = claim_next_campaign("test-api", tmp_path)
    c2 = claim_next_campaign("test-api", tmp_path)

    assert c1 is not None
    assert c2 is not None
    assert c1.campaign_id != c2.campaign_id
    assert c1.claim_counter == 1
    assert c2.claim_counter == 2


def test_claim_exhausted(tmp_path):
    spec = make_minimal_spec()

    generate_campaigns(spec=spec, seed=42, out_dir=tmp_path / "apis" / "test-api" / "campaigns")

    total = len(load_manifest(tmp_path / "apis" / "test-api" / "campaigns" / "manifest.jsonl"))

    for _ in range(total):
        result = claim_next_campaign("test-api", tmp_path)
        assert result is not None

    exhausted = claim_next_campaign("test-api", tmp_path, allow_repetitions=False)
    assert exhausted is None