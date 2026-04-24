import sys
from pathlib import Path
from s4code.query_engine import S4QueryEngine

def main():
    engine = S4QueryEngine(cwd=Path("/home/wxd/LLM/S4Code"))
    agent = engine.bundle.agent
    composer = agent.prompt_composer
    prompt = composer.get_enhanced_prompt(agent)
    print("="*40 + " SYSTEM PROMPT " + "="*40)
    print(prompt)
    print("="*95)

if __name__ == "__main__":
    main()
