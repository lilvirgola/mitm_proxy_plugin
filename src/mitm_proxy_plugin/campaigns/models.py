from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class CampaignMode(str, Enum):
    BASELINE = "baseline"
    SINGLE_MUTANT = "single_mutant"
    MULTI_MUTANT = "multi_mutant"


@dataclass
class CampaignTarget:
    operation_id: str

    def to_dict(self) -> dict:
        return {"operation_id": self.operation_id}

    @classmethod
    def from_dict(cls, data: dict) -> "CampaignTarget":
        return cls(operation_id=data["operation_id"])


@dataclass
class CampaignPolicy:
    max_one_mutant_per_operation: bool = True
    mutate_valid_requests_only: bool = True
    attribution: str = "direct_operation_or_request"

    def to_dict(self) -> dict:
        return {
            "max_one_mutant_per_operation": self.max_one_mutant_per_operation,
            "mutate_valid_requests_only": self.mutate_valid_requests_only,
            "attribution": self.attribution,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CampaignPolicy":
        return cls(
            max_one_mutant_per_operation=data.get(
                "max_one_mutant_per_operation", True
            ),
            mutate_valid_requests_only=data.get(
                "mutate_valid_requests_only", True
            ),
            attribution=data.get(
                "attribution", "direct_operation_or_request"
            ),
        )


@dataclass
class Campaign:
    campaign_id: str
    mode: CampaignMode
    seed: int
    spec_sha256: str
    created_at: str
    target: Optional[CampaignTarget] = None
    mutant: Optional[dict] = None
    assignments: Optional[dict] = None
    policy: CampaignPolicy = field(default_factory=CampaignPolicy)
    claim_counter: Optional[int] = None
    repetition: int = 0
    base_campaign_id: Optional[str] = None

    def to_dict(self) -> dict:
        result = {
            "campaign_id": self.campaign_id,
            "mode": self.mode.value,
            "seed": self.seed,
            "spec_sha256": self.spec_sha256,
            "created_at": self.created_at,
            "policy": self.policy.to_dict(),
            "repetition": self.repetition,
        }

        if self.target is not None:
            result["target"] = self.target.to_dict()

        if self.mutant is not None:
            result["mutant"] = self.mutant

        if self.assignments is not None:
            result["assignments"] = self.assignments

        if self.claim_counter is not None:
            result["claim_counter"] = self.claim_counter

        if self.base_campaign_id is not None:
            result["base_campaign_id"] = self.base_campaign_id

        return result

    @classmethod
    def from_dict(cls, data: dict) -> "Campaign":
        # Parse mode
        mode_raw = data.get("mode", CampaignMode.BASELINE.value)
        try:
            mode = CampaignMode(mode_raw)
        except ValueError:
            mode = CampaignMode.BASELINE

        # Parse target
        target = None
        if "target" in data and data["target"] is not None:
            target = CampaignTarget.from_dict(data["target"])

        # Parse policy
        policy_data = data.get("policy", {})
        policy = CampaignPolicy.from_dict(policy_data)

        return cls(
            campaign_id=data["campaign_id"],
            mode=mode,
            seed=data.get("seed", 0),
            spec_sha256=data.get("spec_sha256", ""),
            created_at=data.get("created_at", ""),
            target=target,
            mutant=data.get("mutant"),
            assignments=data.get("assignments"),
            policy=policy,
            claim_counter=data.get("claim_counter"),
            repetition=data.get("repetition", 0),
            base_campaign_id=data.get("base_campaign_id"),
        )