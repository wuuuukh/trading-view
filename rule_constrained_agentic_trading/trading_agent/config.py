from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_rules(path: str | Path) -> dict[str, Any]:
    """載入交易 SOP 設定；所有門檻應由設定檔管理，避免寫死在策略內。"""
    with Path(path).open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}

