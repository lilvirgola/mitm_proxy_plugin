import json
from pathlib import Path

from mitm_proxy_plugin.core.counter import atomic_increment
from mitm_proxy_plugin.campaigns.models import Campaign


def load_manifest(manifest_path: Path) -> list[dict]:
    if not manifest_path.exists():
        return []

    campaigns = []

    with manifest_path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            campaigns.append(json.loads(line))

    return campaigns

# Atomically claim the next campaign for a given API.
def claim_next_campaign(
    api: str,
    base_dir: Path,
    allow_repetitions: bool = False,
) -> Campaign | None:

    manifest_path = base_dir / "apis" / api / "campaigns" / "manifest.jsonl"

    raw_campaigns = load_manifest(manifest_path)

    if not raw_campaigns:
        return None

    counter_path = base_dir / "state" / "counters" / f"{api}.counter"
    lock_path = base_dir / "state" / "counters" / f"{api}.lock"

    counter = atomic_increment(counter_path, lock_path)

    index = counter - 1

    if index < len(raw_campaigns):
        campaign = Campaign.from_dict(raw_campaigns[index])
        campaign.claim_counter = counter
        campaign.repetition = 0
        campaign.base_campaign_id = campaign.campaign_id
        return campaign

    if not allow_repetitions:
        return None

    # Wrap around for repetitions
    repetition = index // len(raw_campaigns)
    campaign_index = index % len(raw_campaigns)

    campaign = Campaign.from_dict(raw_campaigns[campaign_index])
    campaign.claim_counter = counter
    campaign.repetition = repetition
    campaign.base_campaign_id = campaign.campaign_id
    campaign.campaign_id = (
        f"{campaign.campaign_id}_rep{repetition:02d}"
    )

    return campaign