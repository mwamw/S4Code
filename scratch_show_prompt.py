"""Inspect the product prompt using the public SDK; no model call."""

from pathlib import Path
from s4code.core.agent import S4CodeAgent
from s4code.core.configuration import S4ConfigLoader


def main():
    workspace = Path.cwd()
    settings = S4ConfigLoader().load_agent_settings(workspace)
    with S4CodeAgent.create(workspace=workspace, settings=settings) as agent:
        print(agent.get_enhanced_prompt())


if __name__ == "__main__":
    main()
