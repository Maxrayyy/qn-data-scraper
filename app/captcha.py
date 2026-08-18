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
