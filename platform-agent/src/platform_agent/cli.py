import argparse
from collections.abc import Sequence

from platform_agent.agent import (
    DEFAULT_MAX_TOOL_CALLS,
    run_terraform_module_investigation,
)


def positive_integer(value: str) -> int:
    """Validate positive integer command-line arguments."""
    try:
        parsed_value = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "must be an integer"
        ) from error

    if parsed_value < 1:
        raise argparse.ArgumentTypeError(
            "must be at least 1"
        )

    return parsed_value


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="platform-agent",
        description=(
            "Read-only reliability investigation agent for "
            "AWS platform infrastructure."
        ),
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    inspect_parser = subparsers.add_parser(
        "inspect-module",
        help="Inspect the structure of a Terraform module.",
    )

    inspect_parser.add_argument(
        "module",
        help="Repository-relative module path, such as modules/vpc.",
    )

    inspect_parser.add_argument(
        "--max-tool-calls",
        type=positive_integer,
        default=DEFAULT_MAX_TOOL_CALLS,
        help=(
            "Maximum number of tools the agent may execute "
            f"(default: {DEFAULT_MAX_TOOL_CALLS})."
        ),
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the platform agent CLI."""
    parser = build_parser()
    arguments = parser.parse_args(argv)

    if arguments.command == "inspect-module":
        report = run_terraform_module_investigation(
            module=arguments.module,
            max_tool_calls=arguments.max_tool_calls,
        )

        print(report.model_dump_json(indent=2))

        # Exit 0 when the investigation completed successfully.
        # Exit 2 when safety checks or investigation errors occurred.
        return 2 if report.errors else 0

    parser.error("Unsupported command.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
