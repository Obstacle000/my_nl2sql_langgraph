"""读取 prompts/ 下的提示词模板。"""

from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"


def load_prompt(name: str) -> str:
    return (PROMPT_DIR / f"{name}.prompt").read_text(encoding="utf-8")
