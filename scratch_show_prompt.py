import sys
from pathlib import Path
from s4code.query_engine import S4QueryEngine
from memory import MemoryManage,WorkingMemory,MemoryConfig
from core.request_compiler import compile_prompt_blocks


def main():
    engine = S4QueryEngine(cwd=Path("/home/wxd/LLM/S4Code"))
    agent = engine.bundle.agent
    mm=MemoryManage(config=MemoryConfig(),working_memory=WorkingMemory(MemoryConfig()))
    agent.with_memory(mm)
    composer = agent.prompt_composer
    blocks = composer.get_system_prompt_blocks(agent)
    compiled = compile_prompt_blocks(blocks)
    prompt = composer.get_enhanced_prompt(agent)
    print("="*40 + " SYSTEM PROMPT " + "="*40)
    print(prompt)
    if compiled.runtime_reminder_blocks:
        print("="*39 + " RUNTIME REMINDERS " + "="*39)
        for block in compiled.runtime_reminder_blocks:
            print(f"<system-reminder name=\"{block.name}\">")
            print(block.content)
            print("</system-reminder>")
            print()
    print("="*95)

if __name__ == "__main__":
    main()
