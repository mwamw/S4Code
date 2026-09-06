"""Run with the configured Python environment: python example/sdk_usage.py --help."""

from argparse import ArgumentParser
from pathlib import Path
from s4code.sdk import S4Code


def main() -> None:
    parser = ArgumentParser(description="Use the S4Code Python SDK without a terminal UI.")
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument(
        "--prompt",
        help="Optional model request. Without it, only inspect configuration.",
    )
    parser.add_argument("--resume", help="Existing session ID in this project.")
    args = parser.parse_args()
    with S4Code(cwd=args.cwd) as client:
        session = client.sessions.resume(args.resume) if args.resume else client.sessions.create()
        info = session.info()
        print(
            f"{info.project_root}: {info.provider}/{info.model}"
        )
        if args.prompt:
            result = session.run(args.prompt)
            print(result.text)
            print("Status:", result.status)
            if result.interaction:
                print("User decision required:", result.interaction.model_dump())
        print("Session:", session.id)


if __name__ == "__main__":
    main()
