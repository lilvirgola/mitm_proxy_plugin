import argparse
from pathlib import Path

from mitm_proxy_plugin.openapi.loader import load_spec
from mitm_proxy_plugin.campaigns.generator import generate_campaigns


def main():
    parser = argparse.ArgumentParser(
        description="Generate mutation testing campaigns from an OpenAPI spec."
    )
    parser.add_argument(
        "--spec",
        required=True,
        help="Path to the OpenAPI 3.0 JSON or YAML file.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed for deterministic mutant generation.",
    )
    parser.add_argument(
        "--out-dir",
        default="campaigns",
        help="Directory to write campaign files and manifest.",
    )
    parser.add_argument(
        "--disabled-operators",
        default="",
        help="Comma-separated list of mutation operators to disable.",
    )
    parser.add_argument(
        "--shuffle",
        action="store_true",
        help="Deterministically shuffle campaign order using the seed.",
    )

    args = parser.parse_args()

    spec = load_spec(args.spec)

    disabled_operators = {
        op.strip()
        for op in args.disabled_operators.split(",")
        if op.strip()
    }

    generate_campaigns(
        spec=spec,
        seed=args.seed,
        out_dir=Path(args.out_dir),
        disabled_operators=disabled_operators,
        shuffle=args.shuffle,
    )


if __name__ == "__main__":
    main()