"""配置中枢：yaml + 环境变量双层覆盖。

约定：API key 只走环境变量（configs/default.yaml 中 llm.api_key_env 指定变量名），
任何密钥禁止写入 yaml / 代码 / 仓库（任务书硬性要求）。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "configs" / "default.yaml"


def load_config(path: str | Path | None = None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """加载 yaml 配置并合并 overrides（后者优先）。"""
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    with open(cfg_path, encoding="utf-8") as f:
        cfg: dict[str, Any] = yaml.safe_load(f)
    if overrides:
        cfg = _deep_merge(cfg, overrides)
    return cfg


def load_dotenv(path: str | Path | None = None) -> None:
    """把 .env 中的 KEY=VALUE 注入环境变量（不覆盖已存在的）。"""
    env_path = Path(path) if path else ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def get_api_key(cfg: dict[str, Any]) -> str:
    """从环境变量读取 Hy3 API key；缺失时给出明确报错而非静默失败。"""
    load_dotenv()
    env_name = cfg["llm"].get("api_key_env", "HY3_API_KEY")
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise RuntimeError(
            f"未找到环境变量 {env_name}。请复制 .env.example 为 .env 填写密钥，"
            "或用 setx / $env: 设置后重试（密钥禁止写入配置文件）。"
        )
    return key


def get_base_url(cfg: dict[str, Any]) -> str:
    """端点：环境变量优先，缺省用 configs 中的 base_url_default。"""
    load_dotenv()
    env_name = cfg["llm"].get("base_url_env", "HY3_BASE_URL")
    return os.environ.get(env_name, "").strip() or cfg["llm"].get(
        "base_url_default", "https://tokenhub.tencentmaas.com/v1"
    )


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out
