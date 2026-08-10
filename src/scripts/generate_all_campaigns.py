import argparse
import json
import sys
from pathlib import Path

from mitm_proxy_plugin.openapi.loader import load_spec
from mitm_proxy_plugin.campaigns.generator import generate_campaigns


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--restgym-dir",
        required=True,
        help="Path to the RestGym root directory.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--disabled-operators", default="")
    parser.add_argument("--force", action="store_true", help="Regenerate even if manifest exists.")
    args = parser.parse_args()

    restgym_dir = Path(args.restgym_dir).resolve()
    apis_dir = restgym_dir / "apis"

    if not apis_dir.exists():
        print(f"ERROR: {apis_dir} does not exist.")
        sys.exit(1)

    disabled = {
        op.strip()
        for op in args.disabled_operators.split(",")
        if op.strip()
    }

    for api_dir in sorted(apis_dir.iterdir()):
        if not api_dir.is_dir():
            continue

        api = api_dir.name

        # Skip templates
        if api.startswith("#"):
            continue

        spec_path = api_dir / "specifications" / f"{api}-openapi.json"
        campaigns_dir = api_dir / "campaigns"
        manifest_path = campaigns_dir / "manifest.jsonl"

        if not spec_path.exists():
            print(f"  SKIP {api}: spec not found at {spec_path}")
            continue

        if manifest_path.exists() and not args.force:
            with manifest_path.open() as f:
                count = sum(1 for line in f if line.strip())
            print(f"  OK   {api}: {count} campaigns already exist. Use --force to regenerate.")
            continue

        try:
            spec = load_spec(str(spec_path))
            campaigns = generate_campaigns(
                spec=spec,
                seed=args.seed,
                out_dir=campaigns_dir,
                disabled_operators=disabled,
            )
            print(f"  DONE {api}: generated {len(campaigns)} campaigns.")
        except Exception as e:
            print(f"  ERR  {api}: {e}")


if __name__ == "__main__":
    main()