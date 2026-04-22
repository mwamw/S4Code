from __future__ import annotations
from typing import List, TYPE_CHECKING
from skill.base import BaseSkill, SkillConfig

if TYPE_CHECKING:
    from Tool.BaseTool import Tool

class HelloSkill(BaseSkill):
    """A test skill for verifying local skill loading."""
    def __init__(self):
        config = SkillConfig(
            name="hello",
            description="A test skill from local directory",
            version="1.0.0",
        )
        super().__init__(config)

    def get_tools(self) -> List["Tool"]:
        return []

    def get_prompt(self) -> str:
        return "You have the 'hello' skill installed from your local .s4code/skills directory."
