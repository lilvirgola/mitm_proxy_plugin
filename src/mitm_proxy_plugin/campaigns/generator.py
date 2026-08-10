import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from mitm_proxy_plugin.core.rng import SeededRNG
from mitm_proxy_plugin.mutations.catalog import MutantCatalog
from mitm_proxy_plugin.mutations.taxonomy import enrich_mutant
from mitm_proxy_plugin.campaigns.models import Campaign, CampaignMode, CampaignTarget, CampaignPolicy


def sha256_json(obj: dict) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _write_campaign(out_dir: Path, campaign: Campaign) -> Path:
    path = out_dir / f"{campaign.campaign_id}.json"
    with path.open("w") as f:
        json.dump(campaign.to_dict(), f, indent=2)
    return path


def generate_campaigns(
    spec: dict,
    seed: int,
    out_dir: Path,
    disabled_operators: set[str] | None = None,
    shuffle: bool = False,
) -> list[Campaign]:
    
    spec_hash = sha256_json(spec)
    created_at = datetime.now(timezone.utc).isoformat()

    rng = SeededRNG()
    rng.set_seed(seed)

    catalog = MutantCatalog(
        spec,
        rng,
        disabled_operators=disabled_operators or set(),
    )
    catalog.generate()

    # Collect all mutants with their operation_id
    mutants = []
    for op_id in sorted(catalog.catalog.keys()):
        for mutant in catalog.catalog[op_id]:
            mutant = dict(mutant)
            mutant["operation_id"] = op_id
            mutants.append(mutant)

    # Deterministic base order
    mutants.sort(key=lambda m: m["id"])

    # Optional deterministic shuffle
    if shuffle:
        rng.shuffle(mutants)

    out_dir.mkdir(parents=True, exist_ok=True)

    campaigns: list[Campaign] = []

    # Baseline campaign
    baseline = Campaign(
        campaign_id="c0000_baseline",
        mode=CampaignMode.BASELINE,
        seed=seed,
        spec_sha256=spec_hash,
        created_at=created_at,
        policy=CampaignPolicy(),
    )

    _write_campaign(out_dir, baseline)
    campaigns.append(baseline)

    # Mutation campaigns, one per mutant
    for index, mutant in enumerate(mutants, start=1):
        campaign_id = f"c{index:04d}_{mutant['id']}"

        campaign = Campaign(
            campaign_id=campaign_id,
            mode=CampaignMode.SINGLE_MUTANT,
            seed=seed,
            spec_sha256=spec_hash,
            created_at=created_at,
            target=CampaignTarget(operation_id=mutant["operation_id"]),
            mutant=mutant,
            policy=CampaignPolicy(
                max_one_mutant_per_operation=True,
                mutate_valid_requests_only=True,
                attribution="direct_operation_or_request",
            ),
        )

        _write_campaign(out_dir, campaign)
        campaigns.append(campaign)

    # Write manifest.jsonl
    manifest_path = out_dir / "manifest.jsonl"
    with manifest_path.open("w") as f:
        for campaign in campaigns:
            f.write(json.dumps(campaign.to_dict()) + "\n")

    print(f"Generated {len(campaigns)} campaigns in '{out_dir}'")
    print(f"Manifest written to: {manifest_path}")

    return campaigns