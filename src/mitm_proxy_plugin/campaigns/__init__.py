"""
Campaign management for the MITM proxy plugin.
"""

from mitm_proxy_plugin.campaigns.generator import generate_campaigns, load_manifest
from mitm_proxy_plugin.campaigns.models import (
    Campaign,
    CampaignMode,
    CampaignPolicy,
    CampaignTarget,
)

__all__ = [
    "Campaign",
    "CampaignMode",
    "CampaignPolicy",
    "CampaignTarget",
    "generate_campaigns",
    "load_manifest",
]
