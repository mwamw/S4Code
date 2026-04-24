import sys
from pathlib import Path
from s4code.query_engine import S4QueryEngine

def main():
    engine = S4QueryEngine(cwd=Path("/home/wxd/LLM/S4Code"))
    agent = engine.bundle.agent
    manager = agent.skill_manager
    print("ALL MANIFESTS:")
    for m in manager._collect_skill_manifests():
        print(f"- {m.name}: {m.exposure_mode}")
    print("\nON DEMAND MANIFESTS:")
    for m in manager.get_on_demand_skill_manifests():
        print(f"- {m.name}")

if __name__ == "__main__":
    main()
