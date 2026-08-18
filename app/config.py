"""配置读写与密码简单加密。

注意：此处加密为"防明文裸存"的轻量混淆（机器特征密钥 + XOR + Base64），
并非强加密。任何能读取本机文件的人仍可还原密码。请勿将配置文件外传。
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_URL = (
    "https://loginmyseller.taobao.com/?from=taobaoindex&f=top&style=&sub=true"
    "&redirect_url=https%3A%2F%2Fqn.taobao.com%2Fhome.htm%2Fstarb%2Fnebula"
    "%2Fmkt-tools%2Fmkt-tools-home%2Fhome"
)

_CIPHER_PREFIX = "enc1:"  # 加密标记前缀：不带此前缀的值按明文兼容读取


@dataclass
class AppConfig:
    url: str = DEFAULT_URL
    username: str = ""
    password: str = ""  # 明文，仅存在于内存；落盘时加密
    export_dir: str = ""
    page_timeout: int = 30  # 页面加载超时（秒）


def _derive_key() -> bytes:
    """基于本机特征的派生密钥（换机器后密文不可直接解）。"""
    seed = f"qn-data-scraper-{uuid.getnode()}"
    return hashlib.sha256(seed.encode("utf-8")).digest()


def encrypt_password(plain: str) -> str:
    if not plain:
        return plain
    key = _derive_key()
    raw = bytes(c ^ key[i % len(key)] for i, c in enumerate(plain.encode("utf-8")))
    return _CIPHER_PREFIX + base64.b64encode(raw).decode("ascii")


def decrypt_password(value: str) -> str:
    if not value or not value.startswith(_CIPHER_PREFIX):
        return value  # 旧版本明文兼容
    try:
        key = _derive_key()
        raw = base64.b64decode(value[len(_CIPHER_PREFIX):])
        return bytes(c ^ key[i % len(key)] for i, c in enumerate(raw)).decode("utf-8")
    except Exception:
        return ""  # 解密失败视为无密码


def config_path() -> Path:
    """配置文件位置：Windows 下 %APPDATA%\\qn-data-scraper\\config.json；
    开发环境（非 Windows）用用户主目录。"""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home())
        if not os.access(base, os.W_OK):
            base = Path.home()
        return base / "qn-data-scraper" / "config.json"
    return Path.home() / ".qn-data-scraper" / "config.json"


def save_config(cfg: AppConfig) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(cfg)
    data["password"] = encrypt_password(cfg.password)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_config() -> AppConfig | None:
    path = config_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return AppConfig(
            url=data.get("url") or DEFAULT_URL,
            username=data.get("username", ""),
            password=decrypt_password(data.get("password", "")),
            export_dir=data.get("export_dir", ""),
            page_timeout=int(data.get("page_timeout", 30)),
        )
    except (json.JSONDecodeError, OSError, ValueError, AttributeError):
        return None  # 配置文件损坏 → 视为无配置
