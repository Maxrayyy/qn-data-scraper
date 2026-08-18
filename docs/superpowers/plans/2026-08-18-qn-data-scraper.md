# 千牛数据抓取工具 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 Windows 桌面工具：登录淘宝千牛卖家中心，自动导航至"数据→市场→类目洞察→价格分析"，切换类目"猫笼子/猫别墅"，遍历"分析明细"逐条点击"商品发现"，抓取弹窗商品列表（图片/名称/链接/id/支付单量/件单价）并导出带嵌入图片和超链接的 Excel；打包为无需任何环境的 Windows exe（GitHub Actions 云端构建）。

**Architecture:** PySide6 GUI 在主线程，Playwright 异步 API 跑在 QThread 后台线程的 asyncio 事件循环中；9 个内置步骤集中在 `app/steps.py`（开发者修改区）；纯逻辑模块（config/scraper/excel_export）独立可单测；PyInstaller onedir + 内置 Chromium（`browsers/` 目录，运行时通过 `PLAYWRIGHT_BROWSERS_PATH` 指定），CI 在 windows-latest 上构建。

**Tech Stack:** Python 3.12（CI）/ ≥3.9（本地）、PySide6==6.7.2、playwright==1.45.1、openpyxl==3.1.5、psutil==5.9.8、pyinstaller==6.10.0、pytest==8.2.2、pytest-asyncio==0.23.7

## Global Constraints

- 所有用户可见文案使用中文；日志格式 `[HH:MM:SS][级别] 消息`，级别：info/success/warn/error
- 密码只在内存和加密后的 config.json 中；**任何日志、异常信息不得打印密码明文**
- 所有元素定位器集中定义在 `app/steps.py` 的 `STEP_LOCATORS`；步骤顺序集中定义在 `run_builtin_flow`
- 验证码一律不自动处理：检测到 → 日志提示 → 暂停等人工 → 解除后自动继续（默认最多 600 秒）
- 导出 Excel 绝不覆盖已有文件（重名追加时间戳）；图片嵌入真实图片而非 URL
- 停止任务 = 线程安全关闭浏览器 + 按程序目录精确清理 chromium 进程，绝不误杀用户自装 Chrome
- 网络行为仅限：加载目标页面、下载商品图片；**代码中不得出现任何向第三方上传账号/密码/数据的上传逻辑**
- 打包后 GUI 不得出现命令行黑窗口（PyInstaller `console=False`）
- 每完成一个 Task 立即 git commit（commit message 见各 Task），全部完成后 push 到 origin/main

---

### Task 1: 工程脚手架与开发环境

**Files:**
- Create: `.gitignore`
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `pytest.ini`
- Create: `conftest.py`（空文件，让 pytest 把项目根加入 sys.path）
- Create: `app/__init__.py`（空文件）
- Create: `tests/__init__.py`（空文件）

**Interfaces:**
- Produces: 项目根目录结构、可用的 Python venv（含全部依赖 + playwright chromium 浏览器，供 Task 3+ 的集成测试使用）

- [ ] **Step 1: 创建 .gitignore**

```gitignore
__pycache__/
*.pyc
.pytest_cache/
.venv/
venv/
build/
dist/
browsers/
.DS_Store
*.egg-info/
```

- [ ] **Step 2: 创建 requirements.txt（运行时依赖）**

```
PySide6==6.7.2
playwright==1.45.1
openpyxl==3.1.5
psutil==5.9.8
```

- [ ] **Step 3: 创建 requirements-dev.txt（开发/打包依赖）**

```
pytest==8.2.2
pytest-asyncio==0.23.7
pyinstaller==6.10.0
```

- [ ] **Step 4: 创建 pytest.ini**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 5: 创建空的 conftest.py、app/__init__.py、tests/__init__.py**

```bash
touch conftest.py app/__init__.py tests/__init__.py
```

- [ ] **Step 6: 创建 venv 并安装依赖**

```bash
cd /Users/dongdong/code/qn-data-scraper
python3 --version   # 确认 ≥ 3.9；若系统 python3 过旧，用 conda 建 python=3.12 环境代替
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m playwright install chromium   # 开发机 macOS：装到默认缓存目录（约150MB）
```

- [ ] **Step 7: 验证环境**

```bash
python -c "import playwright, PySide6, openpyxl, psutil, pytest; print('依赖 OK')"
```

Expected: 输出 `依赖 OK`

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "chore: 工程脚手架与依赖清单

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 配置模块（config.py，TDD）

**Files:**
- Create: `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `DEFAULT_URL: str` — 千牛登录页默认 URL
  - `AppConfig` dataclass，字段：`url: str`、`username: str`、`password: str`、`export_dir: str`、`page_timeout: int = 30`
  - `encrypt_password(plain: str) -> str` / `decrypt_password(value: str) -> str`（非加密前缀的值按明文兼容返回）
  - `config_path() -> Path`（Windows: `%APPDATA%\qn-data-scraper\config.json`；非 Windows: `~/.qn-data-scraper/config.json`）
  - `save_config(cfg: AppConfig) -> Path` / `load_config() -> AppConfig | None`（文件不存在或损坏返回 None）

- [ ] **Step 1: 写失败测试 tests/test_config.py**

```python
import json
from pathlib import Path

import pytest

from app.config import (
    AppConfig,
    DEFAULT_URL,
    config_path,
    decrypt_password,
    encrypt_password,
    load_config,
    save_config,
)


def test_encrypt_roundtrip():
    plain = "shouna100"
    cipher = encrypt_password(plain)
    assert cipher != plain                  # 不裸存
    assert not cipher.startswith("shouna")  # 不含明文
    assert decrypt_password(cipher) == plain


def test_encrypt_not_plaintext_in_json():
    cfg = AppConfig(username="u", password="secret123", export_dir="/tmp")
    path = save_config(cfg)
    raw = path.read_text(encoding="utf-8")
    assert "secret123" not in raw


def test_decrypt_plaintext_compat():
    # 旧版本明文值仍可读取
    assert decrypt_password("oldplain") == "oldplain"
    assert decrypt_password("") == ""


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.config_path", lambda: tmp_path / "config.json")
    cfg = AppConfig(url=DEFAULT_URL, username="宠趣汇旗舰店:以安",
                    password="p@ss", export_dir=str(tmp_path), page_timeout=45)
    save_config(cfg)
    loaded = load_config()
    assert loaded is not None
    assert loaded.url == cfg.url
    assert loaded.username == cfg.username
    assert loaded.password == "p@ss"
    assert loaded.page_timeout == 45


def test_load_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.config_path", lambda: tmp_path / "nope.json")
    assert load_config() is None


def test_load_corrupt_returns_none(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    p.write_text("{ not valid json !!!", encoding="utf-8")
    monkeypatch.setattr("app.config.config_path", lambda: p)
    assert load_config() is None


def test_config_path_on_macos(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    p = config_path()
    assert p.name == "config.json"
    assert ".qn-data-scraper" in str(p)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`（或先 `source .venv/bin/activate` 后 `pytest tests/test_config.py -v`）
Expected: 全部 FAIL（`ModuleNotFoundError: No module named 'app.config'`）

- [ ] **Step 3: 实现 app/config.py**

```python
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
    except (json.JSONDecodeError, OSError):
        return None  # 配置文件损坏 → 视为无配置
    return AppConfig(
        url=data.get("url") or DEFAULT_URL,
        username=data.get("username", ""),
        password=decrypt_password(data.get("password", "")),
        export_dir=data.get("export_dir", ""),
        page_timeout=int(data.get("page_timeout", 30)),
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_config.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: 配置读写与密码简单加密模块

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 数据提取模块（scraper.py，TDD）

**Files:**
- Create: `app/scraper.py`
- Test: `tests/test_scraper.py`

**Interfaces:**
- Consumes: Task 1 的 playwright chromium（集成测试用 sync API 打开 fixture 页面）
- Produces:
  - `ProductItem` dataclass，字段：`image_url: str = ""`、`name: str = ""`、`item_url: str = ""`、`product_id: str = ""`、`orders: str = ""`、`price: str = ""`
  - `extract_product_id(url: str) -> str`（支持 `?id=数字`、`/item/数字`、`/数字.htm` 三种形态）
  - `normalize_image_url(url: str) -> str`（`//` 开头补 https:，http 升级 https）
  - `EXTRACT_JS: str` — 弹窗列表提取脚本（表头锚定策略 + 结构回退策略）
  - 备注：本文件与 steps.py 一样是**站点点适配点**，淘宝改版时需同步调整 EXTRACT_JS

- [ ] **Step 1: 写失败测试 tests/test_scraper.py**

```python
from playwright.sync_api import sync_playwright

from app.scraper import EXTRACT_JS, extract_product_id, normalize_image_url


# ---------- 纯函数 ----------

def test_extract_product_id_query():
    assert extract_product_id("https://item.taobao.com/item.htm?id=123456&spm=x") == "123456"


def test_extract_product_id_path():
    assert extract_product_id("https://detail.tmall.com/item/778899.htm") == "778899"


def test_extract_product_id_none():
    assert extract_product_id("https://example.com/foo/bar") == ""


def test_normalize_image_url():
    assert normalize_image_url("//img.alicdn.com/a.jpg") == "https://img.alicdn.com/a.jpg"
    assert normalize_image_url("http://img.alicdn.com/b.jpg") == "https://img.alicdn.com/b.jpg"
    assert normalize_image_url("https://img.alicdn.com/c.jpg") == "https://img.alicdn.com/c.jpg"
    assert normalize_image_url("") == ""


# ---------- EXTRACT_JS 集成测试（fixture 页面） ----------

FIXTURE_WITH_HEADER = """
<div id="popup">
  <div class="header"><span>商品</span><span>支付单量</span><span>件单价</span></div>
  <div class="row">
    <a href="https://item.taobao.com/item.htm?id=111111">
      <img src="//img.alicdn.com/a.jpg"><span>猫别墅A</span>
    </a>
    <span>1,234</span><span>¥99.00</span>
  </div>
  <div class="row">
    <a href="https://item.taobao.com/item.htm?id=222222">
      <img src="//img.alicdn.com/b.jpg"><span>猫笼子B</span>
    </a>
    <span>56</span><span>¥188.5</span>
  </div>
</div>
"""

FIXTURE_NO_HEADER = """
<div id="popup">
  <div class="row"><a href="https://item.taobao.com/item.htm?id=333333">
    <img src="//img.alicdn.com/c.jpg"></a><span>20</span><span>¥50</span></div>
</div>
"""


def _extract(html: str):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html)
        data = page.evaluate(EXTRACT_JS, page.locator("#popup").element_handle())
        browser.close()
        return data


def test_extract_js_with_header_rows():
    data = _extract(FIXTURE_WITH_HEADER)
    assert len(data) == 2
    assert data[0]["name"] == "猫别墅A"
    assert data[0]["href"].endswith("id=111111")
    assert data[0]["img"] == "//img.alicdn.com/a.jpg"
    assert data[0]["orders"] == "1,234"
    assert data[0]["price"] == "¥99.00"
    assert data[1]["name"] == "猫笼子B"


def test_extract_js_no_header_fallback():
    data = _extract(FIXTURE_NO_HEADER)
    assert len(data) == 1
    assert data[0]["href"].endswith("id=333333")
    assert data[0]["orders"] == "20"
    assert data[0]["price"] == "¥50"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_scraper.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.scraper'`）

- [ ] **Step 3: 实现 app/scraper.py**

```python
"""弹窗列表数据提取。

站点点适配点之一（与 steps.py 并列）：淘宝/千牛改版时需要同步调整
EXTRACT_JS（列表行提取规则）与 extract_product_id（URL 规则）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ProductItem:
    image_url: str = ""   # 商品图 URL（已归一化为 https）
    name: str = ""        # 商品名
    item_url: str = ""    # 商品链接
    product_id: str = ""  # 商品id
    orders: str = ""      # 支付单量
    price: str = ""       # 件单价


_ID_PATTERNS = [
    re.compile(r"[?&]id=(\d+)"),
    re.compile(r"/item/(\d+)"),
    re.compile(r"/(\d{6,})\.htm"),
]


def extract_product_id(url: str) -> str:
    for pat in _ID_PATTERNS:
        m = pat.search(url)
        if m:
            return m.group(1)
    return ""


def normalize_image_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http://"):
        return url.replace("http://", "https://", 1)
    return url


# 弹窗列表提取脚本（在页面上下文执行，入参为弹窗根元素）。
# 策略一（表头锚定）：找到文本恰为"件单价"的元素 → 向上找到同时含
#   "支付单量"的表头行 → 以"件单价"在表头行中的列序号定位数据行的两列数值。
# 策略二（结构回退）：无表头时，找"含图片的链接"，其所在行中后两个
#   纯文本兄弟节点依次视为支付单量、件单价。
EXTRACT_JS = """
(root) => {
  const flat = [...root.querySelectorAll('div,li,tr')];
  const hPrice = flat.find(el =>
    (el.textContent || '').trim() === '件单价' && el.children.length <= 2);
  let results = [];
  if (hPrice) {
    // 策略一：表头锚定
    let hRow = hPrice;
    while (hRow && hRow.parentElement) {
      const t = hRow.textContent || '';
      if (t.includes('支付单量') && t.includes('商品')) break;
      hRow = hRow.parentElement;
    }
    if (hRow && hRow.parentElement) {
      const hCells = [...hRow.children];
      let colIdx = hCells.findIndex(c => (c.textContent || '').trim() === '件单价');
      if (colIdx < 0) colIdx = hCells.length - 1;
      const containers = [hRow.parentElement, hRow.parentElement.parentElement, root];
      for (const cont of containers) {
        if (!cont) continue;
        for (const row of cont.children) {
          if (row === hRow || row.contains(hRow)) continue;
          const a = row.querySelector('a[href]');
          const img = row.querySelector('img');
          if (!a || !img) continue;
          const cells = [...row.children];
          results.push({
            name: (a.textContent || '').trim() || img.alt || '',
            href: a.href || '',
            img: img.src || img.dataset.src || '',
            orders: colIdx >= 1 && cells[colIdx - 1] ? (cells[colIdx - 1].textContent || '').trim() : '',
            price: cells[colIdx] ? (cells[colIdx].textContent || '').trim() : '',
          });
        }
        if (results.length) break;
      }
    }
  }
  if (!results.length) {
    // 策略二：结构回退（无表头）
    const anchors = [...root.querySelectorAll('a')].filter(a => a.querySelector('img'));
    for (const a of anchors) {
      let cell = a, row = null;
      for (let i = 0; i < 6 && cell && cell.parentElement && cell.parentElement !== root; i++) {
        const parent = cell.parentElement;
        const sibs = [...parent.children];
        const idx = sibs.indexOf(cell);
        const n1 = sibs[idx + 1], n2 = sibs[idx + 2];
        if (n1 && n2 && !n1.querySelector('a,img') && !n2.querySelector('a,img')) {
          row = { sibs, idx };
          break;
        }
        cell = parent;
      }
      if (!row) continue;
      const img = a.querySelector('img');
      results.push({
        name: (a.textContent || '').trim() || img.alt || '',
        href: a.href || '',
        img: (img && (img.src || img.dataset.src)) || '',
        orders: (row.sibs[row.idx + 1].textContent || '').trim(),
        price: (row.sibs[row.idx + 2].textContent || '').trim(),
      });
    }
  }
  // 按商品链接去重
  const seen = new Set();
  return results.filter(r => seen.has(r.href) ? false : (seen.add(r.href), true));
}
"""
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_scraper.py -v`
Expected: 全部 PASS（6 个纯函数 + 2 个集成）

- [ ] **Step 5: Commit**

```bash
git add app/scraper.py tests/test_scraper.py
git commit -m "feat: 弹窗列表数据提取模块（表头锚定+结构回退）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Excel 导出模块（excel_export.py，TDD）

**Files:**
- Create: `app/excel_export.py`
- Test: `tests/test_excel_export.py`

**Interfaces:**
- Consumes: Task 3 的 `ProductItem`
- Produces:
  - `HEADERS: list[str]` = `["商品图片", "商品名", "商品id", "支付单量", "件单价"]`
  - `build_output_path(export_dir: str | Path, now: datetime | None = None) -> Path`（重名追加 `_%Y%m%d_%H%M%S` 时间戳；`now` 仅供测试注入）
  - `export_to_excel(rows: list[tuple[ProductItem, Path | None]], output_path: Path) -> Path`（rows 中第二个元素为已下载的本地图片路径，None 表示该行无图片）

- [ ] **Step 1: 写失败测试 tests/test_excel_export.py**

```python
import base64
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from app.excel_export import HEADERS, build_output_path, export_to_excel
from app.scraper import ProductItem

# 1x1 透明 PNG（硬编码，避免引入 Pillow）
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _make_item(pid="123456"):
    return ProductItem(
        image_url="https://img.alicdn.com/x.jpg",
        name="猫别墅A",
        item_url=f"https://item.taobao.com/item.htm?id={pid}",
        product_id=pid,
        orders="1,234",
        price="¥99.00",
    )


def test_build_output_path_no_collision(tmp_path):
    p = build_output_path(tmp_path)
    assert p.name == "千牛商品发现数据.xlsx"


def test_build_output_path_collision_append_timestamp(tmp_path):
    (tmp_path / "千牛商品发现数据.xlsx").write_bytes(b"old")
    p = build_output_path(tmp_path, now=datetime(2026, 8, 18, 15, 30, 12))
    assert p.name == "千牛商品发现数据_20260818_153012.xlsx"
    assert p != tmp_path / "千牛商品发现数据.xlsx"  # 不覆盖旧文件


def test_export_headers_values_hyperlink_image(tmp_path):
    img_path = tmp_path / "img.png"
    img_path.write_bytes(PNG_1PX)
    out = export_to_excel(
        [(_make_item(), img_path), (_make_item("999999"), None)],
        tmp_path / "out.xlsx",
    )
    assert out.exists()
    wb = load_workbook(out)
    ws = wb.active
    assert [ws.cell(row=1, column=i).value for i in range(1, 6)] == HEADERS
    assert ws.cell(row=2, column=3).value == "123456"
    assert ws.cell(row=2, column=4).value == "1,234"
    assert ws.cell(row=2, column=5).value == "¥99.00"
    assert ws.cell(row=2, column=2).hyperlink.target.endswith("id=123456")
    assert len(ws._images) == 1          # 第一行有图片，第二行无
    assert ws.row_dimensions[2].height == 64
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_excel_export.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 app/excel_export.py**

```python
"""Excel 导出：真实图片嵌入 + 商品名超链接 + 时间戳防覆盖。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Font, PatternFill

from .scraper import ProductItem

HEADERS = ["商品图片", "商品名", "商品id", "支付单量", "件单价"]
BASE_FILENAME = "千牛商品发现数据"
IMAGE_HEIGHT_PX = 60  # 嵌入图片统一缩略高度（像素）
ROW_HEIGHT = 64       # 数据行高


def build_output_path(export_dir: str | Path, now: datetime | None = None) -> Path:
    """文件名冲突时自动追加时间戳，绝不覆盖旧文件。now 参数仅供测试注入。"""
    now = now or datetime.now()
    d = Path(export_dir)
    path = d / f"{BASE_FILENAME}.xlsx"
    if not path.exists():
        return path
    return d / f"{BASE_FILENAME}_{now:%Y%m%d_%H%M%S}.xlsx"


def export_to_excel(
    rows: list[tuple[ProductItem, Path | None]], output_path: Path
) -> Path:
    """rows: (商品数据, 已下载的本地图片路径；下载失败为 None)。

    多条"商品发现"的数据直接依次追加到同一个工作簿。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "商品发现数据"
    # 表头样式
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="4472C4")
    for col, title in enumerate(HEADERS, start=1):
        c = ws.cell(row=1, column=col, value=title)
        c.font = header_font
        c.fill = header_fill
        c.alignment = Alignment(horizontal="center", vertical="center")
    # 数据行
    for i, (item, img_path) in enumerate(rows, start=2):
        ws.row_dimensions[i].height = ROW_HEIGHT
        # 商品图片：嵌入真实图片（缩略到统一高度，保持宽高比）
        if img_path and img_path.exists():
            img = XLImage(str(img_path))
            img.width = IMAGE_HEIGHT_PX * (img.width / img.height)
            img.height = IMAGE_HEIGHT_PX
            ws.add_image(img, f"A{i}")
        # 商品名：带超链接
        name_cell = ws.cell(row=i, column=2, value=item.name or "(无名称)")
        if item.item_url:
            name_cell.hyperlink = item.item_url
            name_cell.style = "Hyperlink"
        ws.cell(row=i, column=3, value=item.product_id)
        ws.cell(row=i, column=4, value=item.orders)
        ws.cell(row=i, column=5, value=item.price)
        for col in range(1, 6):
            ws.cell(row=i, column=col).alignment = Alignment(vertical="center")
    # 列宽
    for col, width in zip("ABCDE", (16, 46, 20, 12, 12)):
        ws.column_dimensions[col].width = width
    wb.save(output_path)
    return output_path
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_excel_export.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add app/excel_export.py tests/test_excel_export.py
git commit -m "feat: Excel导出模块（嵌入图片+超链接+防覆盖时间戳）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 验证码检测模块（captcha.py，TDD）

**Files:**
- Create: `app/captcha.py`
- Test: `tests/test_captcha.py`

**Interfaces:**
- Consumes: Task 1 的 playwright chromium
- Produces:
  - `describe_captcha(hit: str) -> str`（纯函数：选择器命中字符串 → 中文描述）
  - `async detect_captcha(page: Page) -> str | None`（无验证码返回 None）
  - `async wait_manual_captcha(page: Page, stop_event: threading.Event, log: Callable[[str, str], None], max_wait_seconds: int = 600) -> bool`（True=已解除；False=超时或被停止）

- [ ] **Step 1: 写失败测试 tests/test_captcha.py**

```python
import asyncio
import threading

import pytest
from playwright.sync_api import sync_playwright

from app.captcha import describe_captcha, detect_captcha


# ---------- 纯函数 ----------

def test_describe_captcha():
    assert describe_captcha("#nc_1_wrapper") == "滑块验证"
    assert describe_captcha(".nc-container") == "滑块验证"
    assert describe_captcha("#baxia-dialog-content") == "无痕验证"
    assert describe_captcha("iframe:https://x.com/punish") == "无痕验证"


# ---------- detect_captcha 集成测试（fixture 页面） ----------

def test_detect_captcha_hit():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content('<div id="nc_1_wrapper">滑块</div>')
        assert asyncio.run(detect_captcha(page)) == "滑块验证"
        browser.close()


def test_detect_captcha_miss():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("<div>普通页面</div>")
        assert asyncio.run(detect_captcha(page)) is None
        browser.close()
```

注意：`detect_captcha` 是 async 函数，在 sync playwright 环境中用 `asyncio.run()` 桥接即可（`page.evaluate` 在 async API 下返回 awaitable，直接 run 没有冲突）。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_captcha.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 app/captcha.py**

```python
"""验证码检测与"暂停等人工处理"。

阿里系常见验证码形态：
- 滑块：nc 系（#nc_1_wrapper / .nc-container / .nc_scale）
- 无痕：baxia 对话框（iframe#baxia-dialog-content）
- 通用：iframe src 含 captcha/punish/verify
"""
from __future__ import annotations

import asyncio
import threading
from typing import Callable

from playwright.async_api import Page

DETECT_JS = """
() => {
  const sels = ['#nc_1_wrapper', '.nc-container', '.nc_scale',
                '#baxia-dialog-content', '.baxia-dialog-content',
                '[id*="captcha"]', '[class*="captcha"]', '.captcha-container'];
  for (const sel of sels) {
    const el = document.querySelector(sel);
    if (el && el.offsetParent !== null) return sel;   // 只认可见元素
  }
  const frames = [...document.querySelectorAll('iframe')];
  for (const f of frames) {
    const src = (f.src || '').toLowerCase();
    if (src.includes('captcha') || src.includes('punish') || src.includes('verify')) {
      return 'iframe:' + src;
    }
  }
  return '';
}
"""


def describe_captcha(hit: str) -> str:
    h = hit.lower()
    if "baxia" in h or "punish" in h:
        return "无痕验证"
    if "nc_" in h or "nc-container" in h or "nc-scale" in h:
        return "滑块验证"
    return "验证码"


async def detect_captcha(page: Page) -> str | None:
    """返回验证码中文描述；无验证码返回 None。"""
    try:
        hit = await page.evaluate(DETECT_JS)
    except Exception:
        return None
    return describe_captcha(hit) if hit else None


async def wait_manual_captcha(
    page: Page,
    stop_event: threading.Event,
    log: Callable[[str, str], None],
    max_wait_seconds: int = 600,
) -> bool:
    """暂停等待用户手动完成验证码。返回 True=已解除，False=超时或被停止。"""
    waited = 0
    log("warn", "遇到验证码，请手动处理：请在浏览器窗口中完成验证，完成后工具自动继续…")
    while waited < max_wait_seconds:
        if stop_event.is_set():
            return False
        if not await detect_captcha(page):
            log("success", f"验证码已通过（人工处理耗时约 {waited} 秒），继续执行。")
            return True
        await asyncio.sleep(1)
        waited += 1
        if waited % 10 == 0:
            log("info", f"仍在等待验证码处理…（已等待 {waited} 秒，最长 {max_wait_seconds} 秒）")
    return False
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_captcha.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add app/captcha.py tests/test_captcha.py
git commit -m "feat: 验证码检测与人工等待模块

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 内置操作步骤模块（steps.py，TDD）

**Files:**
- Create: `app/steps.py`
- Test: `tests/test_steps.py`

**Interfaces:**
- Consumes: Task 2 `AppConfig`；Task 3 `ProductItem`/`EXTRACT_JS`/`extract_product_id`/`normalize_image_url`；Task 5 `detect_captcha`/`wait_manual_captcha`
- Produces:
  - `CATEGORY_NAME: str = "猫笼子/猫别墅"`（类目名常量）、`MAX_RETRIES: int = 2`、`CAPTCHA_MAX_WAIT_SECONDS: int = 600`
  - `STEP_LOCATORS: dict[str, list[str]]` — 全部元素候选定位器
  - `class TaskStopped(Exception)`、`class StepFailed(Exception)`
  - `StepsContext` dataclass：`log: Callable[[str, str], None]`、`stop_event: threading.Event`、`timeout_ms: int`、`context: BrowserContext`（用于带会话下载图片）、`temp_dir: Path`、`max_retries: int`
  - `FlowResult` dataclass：`rows: list[tuple[ProductItem, Path | None]]`
  - `async run_builtin_flow(page: Page, cfg: AppConfig, ctx: StepsContext) -> FlowResult`
  - `async _run_step(ctx, step_no: int, name: str, action: Callable[[], Awaitable], page: Page) -> Any`（测试目标）

- [ ] **Step 1: 写失败测试 tests/test_steps.py（只测步骤框架，不测真实网站）**

```python
import asyncio
import threading
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.steps import StepFailed, StepsContext, TaskStopped, _run_step


class FakeLog:
    def __init__(self):
        self.lines = []

    def __call__(self, level, msg):
        self.lines.append((level, msg))

    def text(self):
        return "\n".join(f"[{l}] {m}" for l, m in self.lines)


def make_ctx(max_retries=1):
    log = FakeLog()
    ctx = StepsContext(
        log=log,
        stop_event=threading.Event(),
        timeout_ms=30000,
        context=None,          # 测试不下载图片
        temp_dir=Path("/tmp"),
        max_retries=max_retries,
    )
    return ctx, log


@pytest.mark.asyncio
async def test_run_step_success_first_try():
    ctx, log = make_ctx()
    page = AsyncMock()
    with patch("app.steps.detect_captcha", new=AsyncMock(return_value=None)):
        result = await _run_step(ctx, 1, "测试步骤", lambda: _ok("done"), page)
    assert result == "done"
    assert any("第 1 步『测试步骤』完成" in m for _, m in log.lines)


async def _ok(value):
    await asyncio.sleep(0)
    return value


async def _fail_twice_then_ok(calls):
    calls[0] += 1
    if calls[0] <= 2:
        raise RuntimeError("模拟失败")
    return "recovered"


@pytest.mark.asyncio
async def test_run_step_retries_then_succeeds():
    ctx, log = make_ctx(max_retries=2)
    page = AsyncMock()
    calls = [0]
    with patch("app.steps.detect_captcha", new=AsyncMock(return_value=None)):
        result = await _run_step(ctx, 2, "重试步骤", lambda: _fail_twice_then_ok(calls), page)
    assert result == "recovered"
    assert any("重试" in m for _, m in log.lines)


@pytest.mark.asyncio
async def test_run_step_all_attempts_fail_raises():
    ctx, log = make_ctx(max_retries=1)
    page = AsyncMock()

    async def always_fail():
        raise RuntimeError("坏掉了")

    with patch("app.steps.detect_captcha", new=AsyncMock(return_value=None)):
        with pytest.raises(StepFailed, match="永远失败"):
            await _run_step(ctx, 3, "永远失败", always_fail, page)


@pytest.mark.asyncio
async def test_run_step_stopped_before_start():
    ctx, log = make_ctx()
    ctx.stop_event.set()
    page = AsyncMock()
    with patch("app.steps.detect_captcha", new=AsyncMock(return_value=None)):
        with pytest.raises(TaskStopped):
            await _run_step(ctx, 4, "被停止", lambda: _ok(1), page)


@pytest.mark.asyncio
async def test_run_step_captcha_pause_then_continue():
    ctx, log = make_ctx()
    page = AsyncMock()
    with patch("app.steps.detect_captcha", new=AsyncMock(return_value="滑块验证")) as det, \
         patch("app.steps.wait_manual_captcha", new=AsyncMock(return_value=True)) as wait:
        result = await _run_step(ctx, 5, "验证码步骤", lambda: _ok("pass"), page)
    assert result == "pass"
    det.assert_awaited()
    wait.assert_awaited()
    assert any("滑块验证" in m for _, m in log.lines)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_steps.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 app/steps.py（完整代码）**

```python
"""内置操作步骤（开发者修改区）。

====================================================================
★★★ 修改点击流程 / 元素定位 / 类目名，只需改本文件 ★★★
====================================================================
- STEP_LOCATORS：每个页面元素的候选定位器（按顺序尝试，第一个命中的生效）
- run_builtin_flow：9 个内置步骤的执行顺序（每步一个函数）
- CATEGORY_NAME：要分析的类目名
- 淘宝/千牛改版导致定位失效时，只改这里，GUI 与打包无需变动。
====================================================================
"""
from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from playwright.async_api import BrowserContext, Locator, Page, TimeoutError as PWTimeout

from .captcha import detect_captcha, wait_manual_captcha
from .config import AppConfig
from .scraper import (
    EXTRACT_JS,
    ProductItem,
    extract_product_id,
    normalize_image_url,
)

# ============================ 可调参数 ============================
CATEGORY_NAME = "猫笼子/猫别墅"        # ★ 要分析的类目名
MAX_RETRIES = 2                          # 每步失败自动重试次数
CAPTCHA_MAX_WAIT_SECONDS = 600           # 验证码最长人工等待时间（秒）
LOGIN_SUCCESS_DOMAINS = ["qn.taobao.com"]      # 登录成功判据一：URL 域名
LOGIN_SUCCESS_TEXTS = ["工作台"]               # 登录成功判据二：页面出现标志文字
LOGIN_FAIL_TEXTS = ["密码错误", "账号或密码不正确", "登录名不存在", "验证失败"]

# ============================ 元素定位器 ============================
# 每个键对应一组候选定位器，按顺序尝试，取第一个"可见"的元素。
STEP_LOCATORS: dict[str, list[str]] = {
    # ---- 登录页 ----
    "密码登录页签": [
        "//*[normalize-space()='密码登录']",
        'text="密码登录"',
        "//a[contains(text(),'密码登录')]",
    ],
    "账号输入框": [
        "#fm-login-id",
        "input[name='fm-login-id']",
        "input[placeholder*='账号']",
        "input[placeholder*='会员名']",
    ],
    "密码输入框": [
        "#fm-login-password",
        "input[name='fm-login-password']",
        "input[placeholder*='密码']",
        "input[type='password']",
    ],
    "登录按钮": [
        "button:has-text('登录')",
        "#login-form button[type='submit']",
        ".fm-button",
        "button[type='submit']",
    ],
    # ---- 千牛工作台导航 ----
    "左侧数据菜单": [
        "//span[normalize-space()='数据']",
        'text="数据"',
        "//*[normalize-space()='数据']",
    ],
    "上方市场页签": [
        "//span[normalize-space()='市场']",
        'text="市场"',
        "//*[normalize-space()='市场']",
    ],
    "左侧类目洞察菜单": [
        "//span[normalize-space()='类目洞察']",
        'text="类目洞察"',
        "//*[normalize-space()='类目洞察']",
    ],
    "价格分析页签": [
        "//span[normalize-space()='价格分析']",
        'text="价格分析"',
        "//*[normalize-space()='价格分析']",
        "//a[contains(text(),'价格分析')]",
    ],
    # ---- 价格分析页 ----
    "类目切换区": [
        "//span[contains(text(),'类目')]",
        "[class*='cate-switch']",
        "[class*='cateSwitch']",
        "[class*='category-switch']",
        "[class*='cateName']",
        "[class*='category-name']",
        "[class*='cate-name']",
    ],
    "类目搜索输入框": [
        "input[placeholder*='搜索']",
        "input[placeholder*='类目']",
        "[class*='cate'] input[type='text']",
        "input[type='text']",
    ],
    # ---- 分析明细与弹窗 ----
    "商品发现按钮": [
        "button:has-text('商品发现')",
        "//span[normalize-space()='商品发现']",
        "//*[normalize-space()='商品发现']",
    ],
    "弹窗容器": [
        "[role='dialog']",
        ".next-dialog",
        "[class*='modal']",
        "[class*='dialog']",
        "[class*='drawer']",
    ],
    "弹窗关闭按钮": [
        "[role='dialog'] [class*='close']",
        ".next-dialog-close",
        "[class*='close-btn']",
        "button[aria-label*='关闭']",
        "//span[normalize-space()='×']",
    ],
}


# ============================ 异常与数据类 ============================

class TaskStopped(Exception):
    """任务被用户停止。"""


class StepFailed(Exception):
    """步骤失败（已重试仍失败）。"""


@dataclass
class StepsContext:
    """步骤执行所需的共享上下文。"""
    log: Callable[[str, str], None]
    stop_event: threading.Event
    timeout_ms: int
    context: BrowserContext          # 用于带登录会话下载商品图片
    temp_dir: Path                   # 图片临时目录
    max_retries: int = MAX_RETRIES

    def emit(self, level: str, msg: str) -> None:
        self.log(level, msg)


@dataclass
class FlowResult:
    rows: list[tuple[ProductItem, Path | None]] = field(default_factory=list)


# ============================ 步骤框架 ============================

def _check_stop(ctx: StepsContext) -> None:
    if ctx.stop_event.is_set():
        raise TaskStopped()


async def _run_step(
    ctx: StepsContext,
    step_no: int,
    name: str,
    action: Callable[[], Awaitable],
    page: Page,
):
    """执行一个内置步骤：停止检查 → 执行（失败自动重试）→ 验证码检查 → 中文日志。"""
    ctx.emit("info", f"【第 {step_no} 步】{name}…")
    _check_stop(ctx)
    result = None
    last_err: Exception | None = None
    for attempt in range(1, ctx.max_retries + 2):  # 1 次正式 + N 次重试
        _check_stop(ctx)
        try:
            result = await action()
            break
        except TaskStopped:
            raise
        except PWTimeout as e:
            last_err = e
            ctx.emit("warn", f"第 {step_no} 步『{name}』第 {attempt} 次尝试超时：{str(e).splitlines()[0]}")
        except StepFailed as e:
            last_err = e
            ctx.emit("warn", f"第 {step_no} 步『{name}』第 {attempt} 次尝试失败：{e}")
        except Exception as e:
            last_err = e
            ctx.emit("warn", f"第 {step_no} 步『{name}』第 {attempt} 次尝试失败：{type(e).__name__}: {e}")
        if attempt <= ctx.max_retries:
            ctx.emit("info", f"2 秒后重试（{attempt}/{ctx.max_retries}）…")
            await asyncio.sleep(2)
    else:
        raise StepFailed(f"第 {step_no} 步『{name}』失败：{last_err}")
    # 每步之后统一验证码检查
    hit = await detect_captcha(page)
    if hit:
        ok = await wait_manual_captcha(page, ctx.stop_event, ctx.log, CAPTCHA_MAX_WAIT_SECONDS)
        if not ok:
            if ctx.stop_event.is_set():
                raise TaskStopped()
            raise StepFailed(f"验证码等待超时（{CAPTCHA_MAX_WAIT_SECONDS} 秒未处理），任务终止")
    ctx.emit("success", f"第 {step_no} 步『{name}』完成。")
    return result


async def _locate_first(page: Page, key: str) -> Locator | None:
    """按 STEP_LOCATORS[key] 候选顺序，返回第一个可见元素；全部未命中返回 None。"""
    for sel in STEP_LOCATORS.get(key, []):
        try:
            loc = page.locator(sel)
            n = await loc.count()
            for i in range(min(n, 20)):
                cand = loc.nth(i)
                if await cand.is_visible():
                    return cand
        except Exception:
            continue
    return None


async def _locate_selector_with_hits(page: Page, key: str) -> str | None:
    """返回 STEP_LOCATORS[key] 中第一个存在可见元素的候选定位器字符串。"""
    for sel in STEP_LOCATORS.get(key, []):
        try:
            loc = page.locator(sel)
            n = await loc.count()
            for i in range(min(n, 50)):
                if await loc.nth(i).is_visible():
                    return sel
        except Exception:
            continue
    return None


async def _click_first(page: Page, key: str, name: str) -> None:
    """点击候选定位器中第一个可见元素；找不到则抛 StepFailed。"""
    el = await _locate_first(page, key)
    if el is None:
        raise StepFailed(f"找不到可点击的元素『{name}』，页面可能已改版（请检查 steps.py 定位器）")
    await el.click()


# ============================ 内置步骤 1-9 ============================

async def run_builtin_flow(page: Page, cfg: AppConfig, ctx: StepsContext) -> FlowResult:
    """主流程：依次执行 9 个内置步骤。修改点击顺序改这里。"""
    result = FlowResult()
    await _run_step(ctx, 1, "打开登录页", lambda: _step_open_login(page, cfg, ctx), page)
    await _run_step(ctx, 2, "填写账号密码并登录", lambda: _step_login(page, cfg, ctx), page)
    await _run_step(ctx, 3, "等待登录成功跳转工作台", lambda: _step_wait_login(page, ctx), page)
    await _run_step(ctx, 4, "点击左侧菜单「数据」", lambda: _click_first(page, "左侧数据菜单", "数据"), page)
    await _run_step(ctx, 5, "点击上方页签「市场」", lambda: _click_first(page, "上方市场页签", "市场"), page)
    await _run_step(ctx, 6, "点击左侧菜单「类目洞察」", lambda: _click_first(page, "左侧类目洞察菜单", "类目洞察"), page)
    await _run_step(ctx, 7, "点击「价格分析」", lambda: _click_first(page, "价格分析页签", "价格分析"), page)
    await _run_step(ctx, 8, f"切换类目为「{CATEGORY_NAME}」", lambda: _step_switch_category(page, ctx), page)
    result.rows = await _run_step(
        ctx, 9, "遍历分析明细抓取『商品发现』数据", lambda: _step_collect(page, ctx), page
    )
    return result


# ---- 第 1 步：打开登录页 ----

async def _step_open_login(page: Page, cfg: AppConfig, ctx: StepsContext) -> None:
    await page.goto(cfg.url, wait_until="domcontentloaded", timeout=max(ctx.timeout_ms, 30000))
    await asyncio.sleep(2)


# ---- 第 2 步：登录 ----

async def _step_login(page: Page, cfg: AppConfig, ctx: StepsContext) -> None:
    # 默认可能是扫码登录页，先切到"密码登录"页签
    try:
        tab = await _locate_first(page, "密码登录页签")
        if tab:
            await tab.click()
            await asyncio.sleep(0.5)
    except Exception:
        pass
    for _ in range(3):  # 最多尝试 3 轮（验证码打断会消耗轮次）
        _check_stop(ctx)
        for key, value in (("账号输入框", cfg.username), ("密码输入框", cfg.password)):
            field = await _locate_first(page, key)
            if field is None:
                raise StepFailed(f"找不到{'账号' if '账号' in key else '密码'}输入框，登录页可能已改版")
            await field.fill(value)
        login_btn = await _locate_first(page, "登录按钮")
        if login_btn is None:
            raise StepFailed("找不到登录按钮，登录页可能已改版")
        await login_btn.click()
        await asyncio.sleep(2)
        hit = await detect_captcha(page)
        if not hit:
            return  # 交给第 3 步验证是否真正登录成功
        ctx.emit("warn", f"登录时出现{hit}！请在浏览器窗口中手动完成验证…")
        ok = await wait_manual_captcha(page, ctx.stop_event, ctx.log, CAPTCHA_MAX_WAIT_SECONDS)
        if not ok:
            if ctx.stop_event.is_set():
                raise TaskStopped()
            raise StepFailed("验证码等待超时，登录失败")
        # 验证通过后循环重填重登
    raise StepFailed("多次尝试后仍未完成登录（可能验证码未处理或页面改版）")


# ---- 第 3 步：等待登录成功 ----

async def _step_wait_login(page: Page, ctx: StepsContext) -> None:
    deadline = asyncio.get_event_loop().time() + max(ctx.timeout_ms / 1000 * 3, 90)
    while asyncio.get_event_loop().time() < deadline:
        _check_stop(ctx)
        if any(d in page.url for d in LOGIN_SUCCESS_DOMAINS):
            ctx.emit("success", "登录成功，已跳转到千牛工作台。")
            return
        try:
            body = await page.inner_text("body")
        except Exception:
            body = ""
        if any(t in body for t in LOGIN_SUCCESS_TEXTS):
            ctx.emit("success", "登录成功，已检测到工作台。")
            return
        for bad in LOGIN_FAIL_TEXTS:
            if bad in body:
                raise StepFailed(f"登录失败：页面提示『{bad}』，请检查账号密码")
        await asyncio.sleep(2)
    raise StepFailed("登录超时：等待跳转工作台超过时限，可能遇到验证码或网络问题")


# ---- 第 8 步：切换类目 ----

async def _step_switch_category(page: Page, ctx: StepsContext) -> None:
    switcher = await _locate_first(page, "类目切换区")
    if switcher is None:
        raise StepFailed("找不到类目切换区，请检查 steps.py『类目切换区』定位器")
    await switcher.click()
    input_box = None
    for _ in range(20):
        _check_stop(ctx)
        input_box = await _locate_first(page, "类目搜索输入框")
        if input_box:
            break
        await asyncio.sleep(0.3)
    if input_box is None:
        raise StepFailed("点击类目切换区后未出现搜索输入框")
    await input_box.fill(CATEGORY_NAME)
    await asyncio.sleep(1)
    result = None
    for _ in range(20):
        _check_stop(ctx)
        cands = page.locator(f'//*[normalize-space()="{CATEGORY_NAME}"]')
        n = await cands.count()
        for i in range(min(n, 30)):
            c = cands.nth(i)
            if await c.is_visible():
                result = c
                break
        if result:
            break
        await asyncio.sleep(0.3)
    if result is None:
        raise StepFailed(f"未找到类目搜索结果『{CATEGORY_NAME}』，请确认该类目存在")
    await result.click()
    ctx.emit("success", f"已选择类目：{CATEGORY_NAME}")
    await asyncio.sleep(2)  # 等待价格分析数据刷新


# ---- 第 9 步：遍历分析明细，抓取"商品发现"弹窗 ----

async def _step_collect(page: Page, ctx: StepsContext) -> list[tuple[ProductItem, Path | None]]:
    rows: list[tuple[ProductItem, Path | None]] = []
    processed = 0
    max_guard = 300  # 防御性上限：防止异常情况无限循环
    btn_sel = await _locate_selector_with_hits(page, "商品发现按钮")
    if btn_sel is None:
        raise StepFailed("页面上找不到『商品发现』按钮，请确认已正确到达价格分析页面")
    while processed < max_guard:
        _check_stop(ctx)
        buttons = page.locator(btn_sel)
        n = await buttons.count()
        if processed >= n:
            # 当前可见按钮已处理完：尝试滚动页面加载更多明细
            new_n = await _scroll_page_and_count(page, btn_sel)
            if new_n <= n:
                break
            continue
        ctx.emit("info", f"正在打开第 {processed + 1} 条分析明细的『商品发现』…")
        clicked = False
        for _ in range(2):  # 单条最多尝试 2 次
            _check_stop(ctx)
            btn = page.locator(btn_sel).nth(processed)
            try:
                await btn.scroll_into_view_if_needed()
                await btn.click()
                clicked = True
                break
            except Exception:
                await asyncio.sleep(1)
        if not clicked:
            ctx.emit("warn", f"第 {processed + 1} 条『商品发现』按钮无法点击，跳过。")
            processed += 1
            continue
        popup = await _wait_popup(page, ctx)
        if popup is None:
            ctx.emit("warn", f"第 {processed + 1} 条未检测到弹窗，跳过。")
            processed += 1
            continue
        items = await _extract_popup_items(page, popup, ctx)
        ctx.emit("success", f"第 {processed + 1} 条『商品发现』抓取到 {len(items)} 条商品数据。")
        rows.extend(items)
        await _close_popup(page, popup, ctx)
        processed += 1
    ctx.emit("success", f"分析明细遍历完成，累计抓取 {len(rows)} 条商品数据。")
    return rows


async def _scroll_page_and_count(page: Page, btn_sel: str) -> int:
    """滚动页面到底部（触发懒加载明细），返回滚动后按钮总数。"""
    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1)
    except Exception:
        pass
    return await page.locator(btn_sel).count()


async def _wait_popup(page: Page, ctx: StepsContext) -> Locator | None:
    """等待弹窗出现，返回可见的弹窗容器 Locator。"""
    for _ in range(int(ctx.timeout_ms / 500)):
        _check_stop(ctx)
        for sel in STEP_LOCATORS["弹窗容器"]:
            try:
                loc = page.locator(sel)
                n = await loc.count()
                for i in range(n - 1, -1, -1):  # 新弹窗一般是最后一个
                    cand = loc.nth(i)
                    if await cand.is_visible():
                        return cand
            except Exception:
                continue
        await asyncio.sleep(0.5)
    return None


async def _extract_popup_items(
    page: Page, popup: Locator, ctx: StepsContext
) -> list[tuple[ProductItem, Path | None]]:
    """弹窗内滚动加载到全量后提取数据，并下载商品图片。"""
    prev = -1
    for _ in range(30):  # 最多滚动 30 次，防止死循环
        _check_stop(ctx)
        try:
            data = await popup.evaluate(EXTRACT_JS)
            cur = len(data)
            if cur == prev and cur > 0:
                break
            prev = cur
        except Exception:
            break
        try:
            await popup.evaluate(
                "el => {"
                "  const nodes = [el, ...el.querySelectorAll('*')];"
                "  for (const node of nodes) {"
                "    if (node.scrollHeight > node.clientHeight + 5) {"
                "      node.scrollTop = node.scrollHeight;"
                "    }"
                "  }"
                "}"
            )
        except Exception:
            pass
        await asyncio.sleep(0.8)
    try:
        data = await popup.evaluate(EXTRACT_JS)
    except Exception:
        data = []
    items: list[tuple[ProductItem, Path | None]] = []
    for d in data:
        item = ProductItem(
            image_url=normalize_image_url(d.get("img", "")),
            name=(d.get("name", "") or "").strip(),
            item_url=d.get("href", ""),
            product_id=extract_product_id(d.get("href", "")),
            orders=d.get("orders", ""),
            price=d.get("price", ""),
        )
        img_path = None
        if item.image_url:
            img_path = await _download_image(ctx, item.image_url)
            if img_path is None:
                ctx.emit("warn", f"商品『{item.name[:20]}』图片下载失败，该行仅保留文字。")
        items.append((item, img_path))
    return items


async def _download_image(ctx: StepsContext, url: str) -> Path | None:
    """通过浏览器会话下载图片（复用 Cookie + 带 Referer，规避 CDN 防盗链）。"""
    try:
        resp = await ctx.context.request.get(
            url,
            headers={"Referer": "https://qn.taobao.com/"},
            timeout=ctx.timeout_ms,
        )
        if not resp.ok:
            return None
        body = await resp.body()
        ext = ".img"
        for e in (".jpg", ".png", ".webp", ".gif"):
            if e in url.lower().split("?")[0]:
                ext = e
                break
        path = ctx.temp_dir / f"img_{uuid.uuid4().hex}{ext}"
        path.write_bytes(body)
        return path
    except Exception:
        return None


async def _close_popup(page: Page, popup: Locator, ctx: StepsContext) -> None:
    """优先点关闭按钮，失败则按 Esc。"""
    try:
        close_btn = None
        for sel in STEP_LOCATORS["弹窗关闭按钮"]:
            try:
                loc = page.locator(sel)
                n = await loc.count()
                for i in range(n - 1, -1, -1):
                    cand = loc.nth(i)
                    if await cand.is_visible():
                        close_btn = cand
                        break
            except Exception:
                continue
            if close_btn:
                break
        if close_btn:
            await close_btn.click()
        else:
            await page.keyboard.press("Escape")
    except Exception:
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
    await asyncio.sleep(1)
    try:
        if await popup.is_visible():
            ctx.emit("warn", "弹窗可能未关闭，继续执行前请留意页面状态。")
    except Exception:
        pass
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_steps.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 语法自检**

Run: `python -c "import app.steps; print('steps OK')"`
Expected: `steps OK`

- [ ] **Step 6: Commit**

```bash
git add app/steps.py tests/test_steps.py
git commit -m "feat: 内置9步操作流程（千牛登录→市场→类目洞察→价格分析→抓取）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: 后台工作线程模块（worker.py，TDD）

**Files:**
- Create: `app/worker.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: Task 2 `AppConfig`；Task 4 `build_output_path`/`export_to_excel`；Task 6 `run_builtin_flow`/`TaskStopped`/`StepsContext`
- Produces:
  - `WorkerSignals(QObject)`：`log = Signal(str, str)`、`finished = Signal(bool, str)`
  - `ScrapeWorker(QThread)`：构造入参 `cfg: AppConfig`；方法 `stop() -> None`；属性 `signals`
  - `is_our_browser_proc(name: str, exe: str, app_dir: Path) -> bool`（纯函数，测试目标）
  - `kill_orphan_browsers(app_dir: Path) -> int`（清理本程序目录下的残留 chromium 进程）

- [ ] **Step 1: 写失败测试 tests/test_worker.py（只测纯函数）**

```python
from pathlib import Path

from app.worker import is_our_browser_proc


def test_is_our_browser_true_for_bundled_chromium():
    assert is_our_browser_proc(
        "chrome.exe",
        r"C:\app\千牛数据抓取工具\_internal\browsers\chromium-1148\chrome-win\chrome.exe",
        Path(r"C:\app\千牛数据抓取工具\_internal"),
    )


def test_is_our_browser_false_for_user_chrome():
    assert not is_our_browser_proc(
        "chrome.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        Path(r"C:\app\千牛数据抓取工具\_internal"),
    )


def test_is_our_browser_false_for_non_browser():
    assert not is_our_browser_proc("python.exe", r"C:\app\_internal\python.exe", Path(r"C:\app\_internal"))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_worker.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 app/worker.py（完整代码）**

```python
"""后台工作线程：asyncio 事件循环 + Playwright 生命周期 + 停止与清理。

停止语义（保证"不留后台残留进程"）：
1. GUI 线程调用 stop() → 置停止标志 + call_soon_threadsafe 关闭浏览器；
2. 正在执行的步骤在下一次检查点（_check_stop）抛出 TaskStopped；
3. finally 中依次关闭 context/browser/playwright 驱动；
4. 兜底：kill_orphan_browsers 按"可执行文件位于本程序目录内"精确清理
   残留 chromium 进程——绝不误杀用户自装的 Chrome。
"""
from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
import threading
from pathlib import Path

import psutil
from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright
from PySide6.QtCore import QObject, QThread, Signal

from .config import AppConfig
from .excel_export import build_output_path, export_to_excel
from .steps import StepsContext, TaskStopped, run_builtin_flow


class WorkerSignals(QObject):
    log = Signal(str, str)          # (级别, 消息)
    finished = Signal(bool, str)    # (是否成功, 摘要/错误信息)


class ScrapeWorker(QThread):
    def __init__(self, cfg: AppConfig, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._signals = WorkerSignals()
        self._stop_event = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._temp_dir: Path | None = None

    @property
    def signals(self) -> WorkerSignals:
        return self._signals

    def stop(self) -> None:
        """线程安全停止：置停止标志 + 在主事件循环中关闭浏览器。"""
        self._log("warn", "收到停止指令，正在关闭浏览器…")
        self._stop_event.set()
        loop = self._loop
        if loop and loop.is_running():
            loop.call_soon_threadsafe(self._close_browser)

    def _log(self, level: str, msg: str) -> None:
        self._signals.log.emit(level, msg)

    # ---------- 线程体 ----------

    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._run_async())
        finally:
            try:
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            finally:
                self._loop.close()
                self._loop = None

    async def _run_async(self) -> None:
        try:
            self._log("info", "正在启动内置浏览器（首次启动稍慢，请稍候）…")
            self._temp_dir = Path(tempfile.mkdtemp(prefix="qn-scraper-"))
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=False,  # 有头模式：用户可见并可手动处理验证码
                args=["--disable-blink-features=AutomationControlled"],
            )
            self._context = await self._browser.new_context(
                viewport={"width": 1440, "height": 900},
                locale="zh-CN",
            )
            page = await self._context.new_page()
            page.set_default_timeout(self._cfg.page_timeout * 1000)

            ctx = StepsContext(
                log=self._log,
                stop_event=self._stop_event,
                timeout_ms=self._cfg.page_timeout * 1000,
                context=self._context,
                temp_dir=self._temp_dir,
            )
            result = await run_builtin_flow(page, self._cfg, ctx)

            if result.rows:
                out = build_output_path(self._cfg.export_dir)
                export_to_excel(result.rows, out)
                self._log("success", f"导出成功：共 {len(result.rows)} 条数据 → {out}")
                self._signals.finished.emit(True, f"任务完成！共抓取 {len(result.rows)} 条数据。\nExcel 已保存到：{out}")
            else:
                self._log("warn", "未抓到任何数据，未生成 Excel 文件。")
                self._signals.finished.emit(False, "任务结束，但未抓到任何数据。请检查页面状态或联系开发者调整定位器。")
        except TaskStopped:
            self._log("warn", "任务已停止。")
            self._signals.finished.emit(False, "任务已停止。")
        except Exception as e:
            if self._stop_event.is_set():
                self._log("warn", "任务已停止。")
                self._signals.finished.emit(False, "任务已停止。")
            else:
                self._log("error", f"任务失败：{type(e).__name__}: {e}")
                self._signals.finished.emit(False, f"任务失败：{e}")
        finally:
            await self._cleanup()

    async def _close_browser(self) -> None:
        """在事件循环线程内关闭浏览器（触发在途操作报错 → 流程退出）。"""
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass

    async def _cleanup(self) -> None:
        """关闭浏览器 + 清理临时图片目录 + 兜底清理残留进程。"""
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        self._context = None
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        self._browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._playwright = None
        if self._temp_dir:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None
        # 兜底：清理本程序目录下的残留 chromium 进程
        app_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        killed = kill_orphan_browsers(app_dir)
        if killed:
            self._log("info", f"已清理 {killed} 个残留浏览器进程。")
        else:
            self._log("info", "浏览器已关闭，后台进程已清理。")


# ---------- 进程清理（纯函数 + 扫描） ----------

_BROWSER_NAME_PREFIXES = ("chrome", "headless", "msedge")


def is_our_browser_proc(name: str, exe: str, app_dir: Path) -> bool:
    """判断进程是否为本程序内置的浏览器：名称像浏览器 且 可执行文件位于 app_dir 内。"""
    if not name or not exe:
        return False
    if not name.lower().startswith(_BROWSER_NAME_PREFIXES):
        return False
    try:
        return app_dir.resolve() in Path(exe).resolve().parents
    except Exception:
        return False


def kill_orphan_browsers(app_dir: Path) -> int:
    """杀掉可执行文件位于本程序目录内的浏览器进程（不误伤用户自装浏览器）。"""
    killed = 0
    try:
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                info = proc.info
                if is_our_browser_proc(info.get("name") or "", info.get("exe") or "", app_dir):
                    proc.kill()
                    killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return killed
```

注意：`_cleanup` 里第 1 行构造 tuple 的写法中 `self._context.close if self._context else None` 会把 bound method 存进 tuple——三连判断已经足够，直接写三个独立 try 块更清晰。**实现时用下面这个更直白的版本替换 `_cleanup` 的循环部分：**

```python
    async def _cleanup(self) -> None:
        """关闭浏览器 + 清理临时图片目录 + 兜底清理残留进程。"""
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        self._context = None
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        self._browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._playwright = None
        if self._temp_dir:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None
        # 兜底：清理本程序目录下的残留 chromium 进程
        app_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        killed = kill_orphan_browsers(app_dir)
        if killed:
            self._log("info", f"已清理 {killed} 个残留浏览器进程。")
        else:
            self._log("info", "浏览器已关闭，后台进程已清理。")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_worker.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 语法自检**

Run: `python -c "import app.worker; print('worker OK')"`
Expected: `worker OK`

- [ ] **Step 6: Commit**

```bash
git add app/worker.py tests/test_worker.py
git commit -m "feat: 后台工作线程（停止语义+浏览器进程清理）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: GUI 界面与程序入口（gui.py + main.py，手动冒烟验证）

**Files:**
- Create: `app/gui.py`
- Create: `main.py`

**Interfaces:**
- Consumes: Task 2 `AppConfig`/`DEFAULT_URL`/`save_config`/`load_config`；Task 7 `ScrapeWorker`
- Produces: `MainWindow(QMainWindow)`；`main()` 入口（打包环境设置 `PLAYWRIGHT_BROWSERS_PATH`）

**测试方式：** GUI 无法自动化单测，用以下手动冒烟清单验证（开发机 macOS 有显示器，可直接运行窗口；真实抓取流程留给 Windows 端到端冒烟）。

- [ ] **Step 1: 实现 main.py**

```python
"""程序入口。"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _setup_playwright_browsers() -> None:
    """打包环境：把 Playwright 内置浏览器目录指向程序自带的 browsers/。"""
    if getattr(sys, "frozen", False):  # PyInstaller 打包后
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        browsers = base / "browsers"
        if browsers.is_dir():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers)


def main() -> int:
    _setup_playwright_browsers()
    from PySide6.QtWidgets import QApplication

    from app.gui import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 实现 app/gui.py**

```python
"""主窗口界面（PySide6，纯中文）。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCharFormat
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .config import DEFAULT_URL, AppConfig, load_config, save_config
from .worker import ScrapeWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("千牛数据抓取工具")
        self.resize(820, 640)
        self._worker: ScrapeWorker | None = None
        self._build_ui()
        self._try_auto_load()

    # ---------- 界面搭建 ----------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        form_box = QGroupBox("运行参数")
        form = QFormLayout(form_box)
        self.url_edit = QLineEdit(DEFAULT_URL)
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("淘宝登录账号（支持 主账号:子账号 格式）")
        self.pwd_edit = QLineEdit()
        self.pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)  # 密码掩码，不显示明文
        self.pwd_edit.setPlaceholderText("登录密码")
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Excel 导出文件夹")
        browse_btn = QPushButton("浏览…")
        browse_btn.clicked.connect(self._choose_dir)
        path_row.addWidget(self.path_edit)
        path_row.addWidget(browse_btn)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(5, 600)
        self.timeout_spin.setValue(30)
        self.timeout_spin.setSuffix(" 秒")
        form.addRow("目标网站URL", self.url_edit)
        form.addRow("登录账号", self.user_edit)
        form.addRow("登录密码", self.pwd_edit)
        form.addRow("导出路径", path_row)
        form.addRow("页面加载超时", self.timeout_spin)
        root.addWidget(form_box)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("开始执行")
        self.stop_btn = QPushButton("停止任务")
        self.save_btn = QPushButton("保存配置")
        self.load_btn = QPushButton("加载配置")
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn.clicked.connect(self._on_stop)
        self.save_btn.clicked.connect(self._on_save_config)
        self.load_btn.clicked.connect(self._on_load_config)
        self.stop_btn.setEnabled(False)
        for b in (self.start_btn, self.stop_btn, self.save_btn, self.load_btn):
            b.setMinimumHeight(36)
            btn_row.addWidget(b)
        root.addLayout(btn_row)

        log_box = QGroupBox("运行日志")
        log_layout = QVBoxLayout(log_box)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setStyleSheet("background:#ffffff; color:#1a1a1a;")
        log_layout.addWidget(self.log_view)
        root.addWidget(log_box, stretch=1)

    # ---------- 目录选择 ----------

    def _choose_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "选择 Excel 导出文件夹", self.path_edit.text() or str(Path.home())
        )
        if d:
            self.path_edit.setText(d)

    # ---------- 任务控制 ----------

    def _on_start(self) -> None:
        url = self.url_edit.text().strip()
        user = self.user_edit.text().strip()
        pwd = self.pwd_edit.text()
        out = self.path_edit.text().strip()
        if not url:
            return self._warn("请填写目标网站 URL")
        if not user:
            return self._warn("请填写登录账号")
        if not pwd:
            return self._warn("请填写登录密码")
        if not out or not Path(out).is_dir():
            return self._warn("请选择有效的导出文件夹")
        cfg = AppConfig(
            url=url,
            username=user,
            password=pwd,
            export_dir=out,
            page_timeout=self.timeout_spin.value(),
        )
        self._append_log("info", "任务启动。")
        self._set_running(True)
        self._worker = ScrapeWorker(cfg)
        self._worker.signals.log.connect(self._append_log)
        self._worker.signals.finished.connect(self._on_finished)
        self._worker.start()

    def _on_stop(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.stop()

    def _on_finished(self, success: bool, message: str) -> None:
        self._set_running(False)
        if success:
            QMessageBox.information(self, "任务结束", message)
        else:
            QMessageBox.warning(self, "任务结束", message)

    def _set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        for w in (
            self.url_edit, self.user_edit, self.pwd_edit, self.path_edit,
            self.timeout_spin, self.save_btn, self.load_btn,
        ):
            w.setEnabled(not running)

    # ---------- 配置 ----------

    def _on_save_config(self) -> None:
        cfg = AppConfig(
            url=self.url_edit.text().strip() or DEFAULT_URL,
            username=self.user_edit.text().strip(),
            password=self.pwd_edit.text(),
            export_dir=self.path_edit.text().strip(),
            page_timeout=self.timeout_spin.value(),
        )
        path = save_config(cfg)
        self._append_log("success", f"配置已保存：{path}（密码已加密存储，仅保存在本机）")

    def _on_load_config(self) -> None:
        cfg = load_config()
        if cfg is None:
            self._append_log("warn", "未找到本地配置文件。")
            return
        self.url_edit.setText(cfg.url)
        self.user_edit.setText(cfg.username)
        self.pwd_edit.setText(cfg.password)
        self.path_edit.setText(cfg.export_dir)
        self.timeout_spin.setValue(cfg.page_timeout)
        self._append_log("success", "配置已加载并回填表单。")

    def _try_auto_load(self) -> None:
        """启动时自动加载本地配置（若存在）。"""
        cfg = load_config()
        if cfg is None:
            return
        self.url_edit.setText(cfg.url)
        self.user_edit.setText(cfg.username)
        self.pwd_edit.setText(cfg.password)
        self.path_edit.setText(cfg.export_dir)
        self.timeout_spin.setValue(cfg.page_timeout)

    # ---------- 日志 ----------

    _LEVEL_COLORS = {"info": "#333333", "success": "#1e7d32", "warn": "#b26a00", "error": "#c62828"}

    def _append_log(self, level: str, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(self._LEVEL_COLORS.get(level, "#333333")))
        self.log_view.setCurrentCharFormat(fmt)
        self.log_view.appendPlainText(f"[{ts}][{level.upper()}] {message}")

    def _warn(self, text: str) -> None:
        QMessageBox.warning(self, "提示", text)

    # ---------- 退出清理 ----------

    def closeEvent(self, event) -> None:
        if self._worker and self._worker.isRunning():
            ret = QMessageBox.question(
                self, "确认退出",
                "任务仍在运行，退出将停止任务并关闭浏览器。确定退出吗？",
            )
            if ret != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._worker.stop()
            self._worker.wait(15000)
        event.accept()
```

- [ ] **Step 3: 手动冒烟验证（开发机 macOS）**

Run: `python main.py`
逐项检查：
1. 窗口标题"千牛数据抓取工具"；URL 默认预填千牛登录页地址；
2. 密码框输入字符显示为圆点（掩码）✓
3. 不填账号直接点【开始执行】→ 弹"请填写登录账号"提示；
4. 填任意账号密码、选导出文件夹、点【保存配置】→ 日志显示"配置已保存"；用 `cat ~/.qn-data-scraper/config.json` 确认密码字段以 `enc1:` 开头且不含明文；
5. 清空表单 → 点【加载配置】→ 表单回填成功；
6. 日志框能显示带时间戳和颜色的日志；
7. 关闭窗口无报错。

- [ ] **Step 4: 语法与导入自检**

Run: `python -c "from app.gui import MainWindow; print('gui OK')"`
Expected: `gui OK`

- [ ] **Step 5: Commit**

```bash
git add app/gui.py main.py
git commit -m "feat: PySide6图形界面与程序入口

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: 打包配置（spec + build.bat + GitHub Actions）

**Files:**
- Create: `scraper.spec`
- Create: `build.bat`
- Create: `.github/workflows/build-exe.yml`

**Interfaces:**
- Consumes: 全部模块
- Produces: 可产出 Windows exe 的完整打包链路（CI 自动 + 本地备用）

- [ ] **Step 1: 创建 scraper.spec**

```python
# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：内置 Playwright Chromium，用户无需安装浏览器。

构建前需先执行（build.bat / CI 已内置）：
    set PLAYWRIGHT_BROWSERS_PATH=browsers
    playwright install chromium
"""
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

datas, binaries, hiddenimports = [], [], []
for pkg in ("playwright",):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# greenlet（playwright 依赖的 C 扩展）动态库
binaries += collect_dynamic_libs("greenlet")

# 内置浏览器目录（构建机本地 browsers/ 文件夹，随 exe 一起分发）
import os

if os.path.isdir("browsers"):
    datas += [("browsers", "browsers")]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="千牛数据抓取工具",
    console=False,   # 无命令行黑窗口
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="千牛数据抓取工具",
    upx=False,
)
```

- [ ] **Step 2: 创建 build.bat（Windows 本地一键打包，备用方案）**

```bat
@echo off
chcp 65001 >nul
REM ================================================
REM   千牛数据抓取工具 - Windows 一键打包脚本
REM   双击运行即可（需联网下载依赖，约 5-15 分钟）
REM   前提：已安装 Python 3.12 并勾选 "Add to PATH"
REM ================================================
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.12：https://www.python.org/downloads/
    echo        安装时务必勾选 "Add python.exe to PATH"
    pause & exit /b 1
)

echo [1/4] 安装依赖...
python -m pip install -r requirements.txt -r requirements-dev.txt
if errorlevel 1 (echo [错误] 依赖安装失败 & pause & exit /b 1)

echo [2/4] 下载内置浏览器（约150MB）...
set PLAYWRIGHT_BROWSERS_PATH=browsers
python -m playwright install chromium
if errorlevel 1 (echo [错误] 浏览器下载失败，请检查网络 & pause & exit /b 1)

echo [3/4] 打包 exe（约 3-10 分钟，请耐心等待）...
python -m PyInstaller scraper.spec --noconfirm
if errorlevel 1 (echo [错误] 打包失败，请把报错截图反馈给开发者 & pause & exit /b 1)

echo [4/4] 完成！产物在 dist\千牛数据抓取工具\ 目录，双击 千牛数据抓取工具.exe 即可运行。
pause
```

- [ ] **Step 3: 创建 .github/workflows/build-exe.yml**

```yaml
name: 构建Windows版本exe

on:
  workflow_dispatch: {}   # 允许手动触发
  push:
    branches: [main]

jobs:
  build-windows:
    runs-on: windows-latest
    env:
      PLAYWRIGHT_BROWSERS_PATH: browsers
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: 安装依赖
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt -r requirements-dev.txt

      - name: 下载内置浏览器
        run: python -m playwright install chromium

      - name: 运行单元测试
        run: pytest tests/ -q

      - name: 打包 exe
        run: python -m PyInstaller scraper.spec --noconfirm

      - name: 上传产物
        uses: actions/upload-artifact@v4
        with:
          name: 千牛数据抓取工具-Windows版
          path: dist/千牛数据抓取工具/
          retention-days: 90
```

- [ ] **Step 4: 本地验证 spec 语法（不执行打包）**

Run: `python -c "import ast; ast.parse(open('scraper.spec').read()); print('spec 语法 OK')"`
Expected: `spec 语法 OK`

- [ ] **Step 5: Commit**

```bash
git add scraper.spec build.bat .github/workflows/build-exe.yml
git commit -m "build: PyInstaller打包配置与GitHub Actions云端构建

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: README 使用说明与开发者文档，最终推送

**Files:**
- Create: `README.md`

**Interfaces:**
- Consumes: 全部
- Produces: 用户手册（普通用户）+ 开发者文档（内置步骤修改指南、打包指南、故障排查）

- [ ] **Step 1: 创建 README.md**

```markdown
# 千牛数据抓取工具

Windows 桌面工具：自动登录淘宝千牛卖家中心 → 导航到"数据 → 市场 → 类目洞察 → 价格分析"→ 切换类目"猫笼子/猫别墅" → 遍历"分析明细"逐条抓取"商品发现"弹窗数据 → 导出 Excel（图片真实嵌入 + 商品名带超链接）。

**目标电脑无需安装 Python、浏览器或任何环境，解压即用。**

---

## 一、普通用户使用说明

### 1. 获取软件

1. 打开仓库的 [Actions](../../actions) 页面；
2. 点击最近一次**成功**的构建（绿色 ✓）；
3. 页面底部 **Artifacts** 区域下载 `千牛数据抓取工具-Windows版`；
4. 解压 zip，得到文件夹 `千牛数据抓取工具/`；
5. 双击其中的 `千牛数据抓取工具.exe` 启动（首次启动稍慢，属正常现象）。

> 提示：下载产物保留 90 天，过期后到 Actions 页面手动点一次 "Re-run all jobs"（或让开发者重新构建）即可。

### 2. 使用步骤

1. 填写表单：目标网站 URL（已默认填好千牛登录页）、登录账号（支持 `主账号:子账号` 格式）、登录密码（掩码显示）；
2. 点【浏览…】选择 Excel 导出文件夹；
3. 【页面加载超时】一般保持默认 30 秒即可；
4. 点【开始执行】。程序会自动打开一个浏览器窗口并执行整套流程，**请勿手动操作该浏览器**（处理验证码时除外）；
5. 如出现滑块/无痕验证码，工具会暂停并提示"遇到验证码，请手动处理"——在浏览器窗口里手动滑一下，验证通过后工具自动继续；
6. 完成后弹出提示，Excel 保存在你选择的文件夹里，文件名 `千牛商品发现数据.xlsx`（若同名文件已存在，自动加时间戳，绝不覆盖旧文件）。

### 3. 常见故障排查

| 现象 | 原因 | 处理办法 |
|---|---|---|
| 双击 exe 无反应 | 被杀毒软件拦截 | 添加信任/白名单后重试 |
| 日志提示"找不到账号输入框" | 淘宝登录页改版 | 联系开发者更新定位器 |
| 登录后一直提示验证码 | 新设备登录风控 | 多手动完成几次验证，或用常用网络环境 |
| 日志提示"登录失败：密码错误" | 账号密码有误 | 检查账号格式（子账号需 `主账号:子账号`） |
| 抓取条数为 0 或数据错位 | 千牛页面改版 | 联系开发者调整 steps.py / scraper.py |
| Excel 里某行没有图片 | 该图片下载失败（网络/CDN） | 不影响文字数据，重跑一次通常可解决 |
| 点【停止任务】后浏览器没关 | 偶发进程残留 | 任务管理器结束 `headless_shell.exe` / `chrome.exe` 中位于本工具文件夹内的进程 |

### 4. 隐私说明

- 账号密码仅保存在本机配置文件中（密码已加密混淆存储），**不会上传到任何网络**；
- 抓取的数据与图片只写入本地 Excel；程序唯一的网络行为是访问淘宝页面与商品图片 CDN。

---

## 二、开发者文档

### 1. 本地开发环境（macOS/Linux）

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m playwright install chromium
python main.py          # 运行 GUI
pytest tests/ -v        # 运行测试
```

### 2. ★ 修改内置点击步骤（改版适配）

**所有定位器与步骤顺序都在 `app/steps.py` 一个文件里：**

- **`CATEGORY_NAME`**（文件顶部）：要分析的类目名；
- **`STEP_LOCATORS`**：每个界面元素的候选定位器列表。改版后页面元素变了，改这里即可；支持任意 Playwright 定位语法（CSS / `text=` / XPath），按顺序尝试，取第一个可见的；
- **`run_builtin_flow`**：9 个内置步骤的执行顺序。增删步骤、调整顺序改这个函数；每个步骤是一个函数，参考现有写法新增即可；
- **`_step_collect` / `_wait_popup`**：分析明细遍历与弹窗处理逻辑；
- **`app/scraper.py` 的 `EXTRACT_JS`**：弹窗内"三列列表"的提取规则（表头锚定 + 结构回退两种策略），列表结构变化时改这里；
- 步骤框架（`_run_step`）自动提供：中文日志、失败重试 2 次、每步后验证码检测，新增步骤无需自己处理这些。

**适配新页面建议流程**：用浏览器开发者工具（F12）检查目标元素的 id/class/文本 → 在 `STEP_LOCATORS` 加候选定位器 → `python main.py` 本地跑通 → 提交构建。

### 3. 打包出 exe

**方式一（推荐）：GitHub Actions 云端构建**
推到 `main` 分支自动触发；或 Actions 页面手动 "Run workflow"。产物下载见上文。

**方式二：Windows 本地构建**
任意 Windows 电脑安装 Python 3.12（勾选 Add to PATH），双击 `build.bat`，产物在 `dist\千牛数据抓取工具\`。

### 4. 打包常见坑

| 问题 | 解决办法 |
|---|---|
| 打包后报 "Executable doesn't exist ... node.exe" | 确认 spec 里 `collect_all("playwright")` 生效，pyinstaller 版本 ≥ 6.0 |
| 打包后浏览器启动失败 | 确认 `browsers/` 目录在打包时存在（先执行 `set PLAYWRIGHT_BROWSERS_PATH=browsers && playwright install chromium`），且 `main.py` 中 `_setup_playwright_browsers` 正确设置了环境变量 |
| exe 启动闪退 | 临时用 `console=True` 重新打包，从控制台错误信息定位问题 |
| PySide6 打包体积大 | 正常现象（Qt 体积大）；如需瘦身可在 spec 的 excludes 里追加未用的 Qt 模块 |

### 5. 测试

- 纯逻辑单测：`pytest tests/`（CI 每次构建都会先跑测试，失败则不打包）；
- 端到端冒烟清单（Windows 上拿真实账号跑一次）：
  1. 填真实账号密码 → 开始执行 → 观察 9 步日志依次出现；
  2. 出现验证码时确认工具暂停、人工处理后自动继续；
  3. 观察日志"第 N 条『商品发现』抓取到 X 条商品数据"；
  4. 打开导出的 Excel：5 列表头正确、图片可见、商品名可点击跳转、数据无错位；
  5. 中途点【停止任务】→ 浏览器全部关闭，任务管理器无残留 headless_shell/chrome（本工具目录内）进程。
```

- [ ] **Step 2: 全量测试与收尾检查**

```bash
pytest tests/ -v
git status   # 确认无遗漏文件
```

Expected: 全部测试 PASS；工作区干净（或只有预期文件）

- [ ] **Step 3: 最终提交并推送**

```bash
git add README.md
git commit -m "docs: 使用说明与开发者文档

Co-Authored-By: Claude <noreply@anthropic.com>"
git push origin main
```

- [ ] **Step 4: 触发云端构建**

推送后 GitHub Actions 自动开始构建（约 10 分钟）。构建完成后通知用户到 Actions 页面下载 `千牛数据抓取工具-Windows版` 产物，并按 README"端到端冒烟清单"验证。

---

## 自审记录

**Spec 覆盖检查：**
- URL/账号/密码输入框 ✓（Task 8 GUI）；密码掩码 ✓（EchoMode.Password）；导出路径选择 ✓（Task 8）；超时秒数输入 ✓（Task 8）
- 开始执行/停止任务/保存配置/加载配置 ✓（Task 8；停止与清理 Task 7）
- 实时中文日志 + 不闪退 ✓（Task 7 worker 全局捕获 + Task 8 日志框）
- 内置浏览器打包 ✓（Task 9 spec + browsers/ + PLAYWRIGHT_BROWSERS_PATH）
- 步骤内置固化、开发者改 steps.py ✓（Task 6）
- 表格自动识别、Excel 行列转换 ✓（Task 3/4）；重名时间戳 ✓（Task 4）
- 异常容错中文提示 ✓（Task 6 _run_step）；停止清理进程 ✓（Task 7）
- 验证码不自动处理、暂停人工 ✓（Task 5/6）
- 无上传逻辑 ✓（全部模块只有页面访问与图片下载）
- 交付物：源码 ✓、打包脚本 ✓、README ✓（Task 10）；exe 由 CI 产出
- 无黑窗口 ✓（console=False）

**类型一致性检查：**
- `ProductItem` 字段在 Task 3 定义，Task 4/6 引用一致 ✓
- `StepsContext` 字段（log/stop_event/timeout_ms/context/temp_dir/max_retries）在 Task 6 定义，Task 7 构造时字段名一致 ✓
- `export_to_excel(rows: list[tuple[ProductItem, Path | None]], output_path: Path) -> Path` 与 Task 7 调用一致 ✓
- `build_output_path(export_dir, now=None)` 与 Task 7 调用（只传 export_dir）一致 ✓
- `wait_manual_captcha(page, stop_event, log, max_wait_seconds)` 在 Task 5 定义，Task 6 调用一致 ✓
- `_run_step(ctx, step_no, name, action, page)` 在 Task 6 定义，测试一致 ✓
- `is_our_browser_proc(name, exe, app_dir)` 在 Task 7 定义，测试一致 ✓
- `run_builtin_flow(page, cfg, ctx) -> FlowResult` 与 Task 7 调用一致 ✓
- `WorkerSignals.log/finished` 信号在 Task 7 定义，Task 8 连接一致 ✓
