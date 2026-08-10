"""
Campaign management for the MITM proxy plugin.
"""

from mitm_proxy_plugin.campaigns.models import (
    Campaign,
    CampaignMode,
    CampaignTarget,
    CampaignPolicy,
)
from mitm_proxy_plugin.campaigns.generator import generate_campaigns
from mitm_proxy_plugin.campaigns.claimer import claim_next_campaign, load_manifest

__all__ = [
    "Campaign",
    "CampaignMode",
    "CampaignTarget",
    "CampaignPolicy",
    "generate_campaigns",
    "claim_next_campaign",
    "load_manifest",
]