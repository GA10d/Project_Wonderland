from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
CELL = 32
STYLE = "limezu-modern-16"


def load_credentials(root: Path = ROOT) -> str:
    """Accept a dotenv file or a single bare key; never log its contents."""
    if os.getenv("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    path = root / "key.env"
    if not path.exists():
        raise RuntimeError("请在 key.env 配置 OPENAI_API_KEY，或设置同名环境变量。")
    content = path.read_text(encoding="utf-8-sig").strip()
    if content.startswith("sk-") and not any(c.isspace() for c in content):
        return content
    values = dotenv_values(path)
    key = values.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("key.env 需要 OPENAI_API_KEY=... 或单独一行 API key。")
    return key


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    llm_model: str = "gpt-6-astra"
    image_model: str = "gpt-image-2.5-sunburst"
    image_quality: str = "high"
    max_new_assets: int = 3
    max_image_attempts: int = 2

    @classmethod
    def load(cls, root: Path = ROOT) -> "Settings":
        import tomllib
        path = root / "config.toml"
        values = tomllib.loads(path.read_text()) if path.exists() else {}
        return cls(root=root, **values.get("models", {}), **values.get("generation", {}))

    def client(self):
        from openai import OpenAI
        return OpenAI(api_key=load_credentials(self.root), timeout=240, max_retries=0)
