"""
Campaign Manifest Generator for RESTberus Mutation Testing.

Generates mutation campaign manifests (JSONL) from OpenAPI specifications.
Supports both single-spec and directory-scan modes.

Usage examples:
  # Single spec mode (quick testing):
  python generate_manifest.py --spec path/to/openapi.json --out manifests/

  # RestGym directory mode (batch generation):
  python generate_manifest.py --restgym-dir /path/to/restgym --seed 42

  # RESTberus directory mode (Train Ticket):
  python generate_manifest.py --restberus-dir /path/to/RESTberus --api ts-auth-service

  # With operator filtering:
  python generate_manifest.py --spec spec.json --operators Simulate502,MalformedJSON

  # Dry run (preview without writing):
  python generate_manifest.py --spec spec.json --dry-run
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from mitm_proxy_plugin.openapi.loader import load_spec
from mitm_proxy_plugin.campaigns.generator import generate_campaigns
from mitm_proxy_plugin.campaigns.models import Campaign


def print_summary(campaigns: list[Campaign], api_name: str) -> None:
    """Print a summary table of generated campaigns."""
    operator_counts = Counter()
    taxonomy_counts = Counter()

    for c in campaigns:
        if c.mutant:
            op = c.mutant.get("operator", "unknown")
            operator_counts[op] += 1
            taxonomy = c.mutant.get("taxonomy_path", "unknown")
            taxonomy_counts[taxonomy.split(".")[0] if taxonomy else "unknown"] += 1

    total_mutants = sum(operator_counts.values())
    baseline_count = sum(1 for c in campaigns if c.mode.value == "baseline")

    print(f"\n{'='*60}")
    print(f"  Campaign Summary: {api_name}")
    print(f"{'='*60}")
    print(f"  Total campaigns: {len(campaigns)}")
    print(f"  Baseline runs:   {baseline_count}")
    print(f"  Mutant runs:     {total_mutants}")
    print(f"\n  {'Operator':<25} {'Count':>6}")
    print(f"  {'-'*33}")
    for op, count in sorted(operator_counts.items(), key=lambda x: -x[1]):
        print(f"  {op:<25} {count:>6}")
    print(f"\n  {'Taxonomy Category':<25} {'Count':>6}")
    print(f"  {'-'*33}")
    for cat, count in sorted(taxonomy_counts.items(), key=lambda x: -x[1]):
        print(f"  {cat:<25} {count:>6}")
    print(f"{'='*60}\n")


def generate_for_spec(
    spec_path: Path,
    out_dir: Path,
    seed: int,
    disabled_operators: set[str] | None = None,
    enabled_operators: set[str] | None = None,
    max_per_operation: int | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> int:
    """Generate campaigns for a single OpenAPI spec. Returns count generated."""
    manifest_path = out_dir / "manifest.jsonl"

    # Skip if manifest exists and not forcing
    if manifest_path.exists() and not force and not dry_run:
        with manifest_path.open() as f:
            count = sum(1 for line in f if line.strip())
        print(f"  OK   {spec_path.name}: {count} campaigns exist. Use --force to regenerate.")
        return 0

    if not spec_path.exists():
        print(f"  ERR  {spec_path.name}: spec not found at {spec_path}")
        return 0

    try:
        spec = load_spec(str(spec_path))
    except Exception as e:
        print(f"  ERR  {spec_path.name}: failed to parse spec: {e}")
        return 0

    # Apply operator filtering
    if enabled_operators:
        # Whitelist mode: disable everything NOT in the whitelist
        from mitm_proxy_plugin.mutations.operators import OPERATOR_NAMES
        disabled_operators = OPERATOR_NAMES - enabled_operators
    
    campaigns = generate_campaigns(
        spec=spec,
        seed=seed,
        out_dir=out_dir if not dry_run else Path("/tmp/dry_run"),
        disabled_operators=disabled_operators or set(),
    )

    # Apply per-operation limit
    if max_per_operation and len(campaigns) > max_per_operation:
        # Keep baseline + first N mutants per operation
        from collections import defaultdict
        from mitm_proxy_plugin.campaigns.models import CampaignMode

        limited = []
        op_counts = defaultdict(int)

        for c in campaigns:
            if c.mode == CampaignMode.BASELINE:
                limited.append(c)
            else:
                op_id = c.target.operation_id if c.target else "unknown"
                if op_counts[op_id] < max_per_operation:
                    limited.append(c)
                    op_counts[op_id] += 1

        campaigns = limited

    # Print summary
    print_summary(campaigns, spec_path.stem)

    if dry_run:
        print(f"  DRY RUN: Would write {len(campaigns)} campaigns to {manifest_path}")
        return len(campaigns)

    # Write manifest
    out_dir.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8") as f:
        for campaign in campaigns:
            f.write(json.dumps(campaign.to_dict()) + "\n")

    print(f"  DONE {spec_path.name}: wrote {len(campaigns)} campaigns to {manifest_path}")
    return len(campaigns)


def scan_restgym_dir(
    restgym_dir: Path,
    seed: int,
    disabled_operators: set[str] | None = None,
    enabled_operators: set[str] | None = None,
    max_per_operation: int | None = None,
    dry_run: bool = False,
    force: bool = False,
    api_filter: str | None = None,
) -> None:
    """Scan a RestGym directory and generate campaigns for all APIs."""
    apis_dir = restgym_dir / "apis"

    if not apis_dir.exists():
        print(f"ERROR: {apis_dir} does not exist.")
        sys.exit(1)

    total_generated = 0
    total_skipped = 0

    for api_dir in sorted(apis_dir.iterdir()):
        if not api_dir.is_dir() or api_dir.name.startswith("#"):
            continue

        api_name = api_dir.name

        # Apply API filter if specified
        if api_filter and api_filter not in api_name:
            continue

        spec_path = api_dir / "specifications" / f"{api_name}-openapi.json"
        campaigns_dir = api_dir / "campaigns"

        count = generate_for_spec(
            spec_path=spec_path,
            out_dir=campaigns_dir,
            seed=seed,
            disabled_operators=disabled_operators,
            enabled_operators=enabled_operators,
            max_per_operation=max_per_operation,
            dry_run=dry_run,
            force=force,
        )

        if count > 0:
            total_generated += count
        else:
            total_skipped += 1

    print(f"\n{'='*60}")
    print(f"  Batch Complete")
    print(f"{'='*60}")
    print(f"  APIs processed: {total_generated + total_skipped}")
    print(f"  APIs generated: {total_generated}")
    print(f"  APIs skipped:   {total_skipped}")
    print(f"{'='*60}")


def scan_restberus_dir(
    restberus_dir: Path,
    seed: int,
    disabled_operators: set[str] | None = None,
    enabled_operators: set[str] | None = None,
    max_per_operation: int | None = None,
    dry_run: bool = False,
    force: bool = False,
    api_filter: str | None = None,
) -> None:
    """Scan RESTberus directory for Train Ticket OpenAPI specs."""
    # RESTberus stores specs in apis/ directory
    apis_dir = restberus_dir / "apis"
    
    if not apis_dir.exists():
        print(f"ERROR: {apis_dir} does not exist.")
        sys.exit(1)

    total_generated = 0

    for api_dir in sorted(apis_dir.iterdir()):
        if not api_dir.is_dir():
            continue

        api_name = api_dir.name

        # Apply API filter
        if api_filter and api_filter not in api_name:
            continue

        # RESTberus spec naming convention
        spec_path = api_dir / "openapi.json"
        if not spec_path.exists():
            spec_path = api_dir / "specifications" / f"{api_name}-openapi.json"
        if not spec_path.exists():
            continue

        # Output to a manifests/ directory in RESTberus root
        out_dir = restberus_dir / "manifests" / api_name

        count = generate_for_spec(
            spec_path=spec_path,
            out_dir=out_dir,
            seed=seed,
            disabled_operators=disabled_operators,
            enabled_operators=enabled_operators,
            max_per_operation=max_per_operation,
            dry_run=dry_run,
            force=force,
        )

        if count > 0:
            total_generated += count

    print(f"\n  RESTberus scan complete: {total_generated} campaigns generated.")


def main():
    parser = argparse.ArgumentParser(
        description="Generate mutation campaign manifests from OpenAPI specifications.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single spec (quick test):
  %(prog)s --spec path/to/openapi.json --out manifests/ --dry-run

  # RestGym batch:
  %(prog)s --restgym-dir /path/to/restgym --seed 42

  # RESTberus Train Ticket (specific API):
  %(prog)s --restberus-dir /path/to/RESTberus --api ts-auth-service

  # Only Execution Faults:
  %(prog)s --spec spec.json --operators Simulate502,Simulate503,Simulate500

  # Limit mutants per operation (for MVP testing):
  %(prog)s --spec spec.json --max-per-operation 5
        """,
    )

    # Input mode (mutually exclusive)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--spec",
        type=Path,
        help="Path to a single OpenAPI spec file (JSON/YAML).",
    )
    input_group.add_argument(
        "--restgym-dir",
        type=Path,
        help="Path to the RestGym root directory (scans apis/ subdirectory).",
    )
    input_group.add_argument(
        "--restberus-dir",
        type=Path,
        help="Path to the RESTberus root directory (scans apis/ subdirectory).",
    )

    # Output
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory for single-spec mode. Defaults to ./campaigns/.",
    )

    # Filtering
    parser.add_argument(
        "--api",
        type=str,
        default=None,
        help="Filter to a specific API name (substring match).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic generation (default: 42).",
    )
    parser.add_argument(
        "--disabled-operators",
        type=str,
        default="",
        help="Comma-separated list of operators to DISABLE (e.g., 'Timeout,ConnectionDrop').",
    )
    parser.add_argument(
        "--operators",
        type=str,
        default="",
        help="Comma-separated list of operators to ENABLE (whitelist mode).",
    )
    parser.add_argument(
        "--max-per-operation",
        type=int,
        default=None,
        help="Maximum number of mutants to generate per operation (limits manifest size).",
    )

    # Behavior
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview generation without writing files.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even if manifest.jsonl already exists.",
    )

    args = parser.parse_args()

    # Parse operator filters
    disabled = {op.strip() for op in args.disabled_operators.split(",") if op.strip()} or None
    enabled = {op.strip() for op in args.operators.split(",") if op.strip()} or None

    if enabled and disabled:
        print("ERROR: Cannot use both --operators (whitelist) and --disabled-operators (blacklist).")
        sys.exit(1)

    # Route to appropriate mode
    if args.spec:
        # Single spec mode
        out_dir = args.out or Path("campaigns")
        generate_for_spec(
            spec_path=args.spec.resolve(),
            out_dir=out_dir,
            seed=args.seed,
            disabled_operators=disabled,
            enabled_operators=enabled,
            max_per_operation=args.max_per_operation,
            dry_run=args.dry_run,
            force=args.force,
        )

    elif args.restgym_dir:
        # RestGym directory mode
        scan_restgym_dir(
            restgym_dir=args.restgym_dir.resolve(),
            seed=args.seed,
            disabled_operators=disabled,
            enabled_operators=enabled,
            max_per_operation=args.max_per_operation,
            dry_run=args.dry_run,
            force=args.force,
            api_filter=args.api,
        )

    elif args.restberus_dir:
        # RESTberus directory mode
        scan_restberus_dir(
            restberus_dir=args.restberus_dir.resolve(),
            seed=args.seed,
            disabled_operators=disabled,
            enabled_operators=enabled,
            max_per_operation=args.max_per_operation,
            dry_run=args.dry_run,
            force=args.force,
            api_filter=args.api,
        )


if __name__ == "__main__":
    main()