import asyncio
import threading
from unittest.mock import AsyncMock, patch

import pytest
from playwright.async_api import async_playwright

from app.captcha import describe_captcha, detect_captcha, wait_manual_captcha


# ---------- 纯函数 ----------

def test_describe_captcha():
    assert describe_captcha("#nc_1_wrapper") == "滑块验证"
    assert describe_captcha(".nc-container") == "滑块验证"
    assert describe_captcha("#baxia-dialog-content") == "无痕验证"
    assert describe_captcha("iframe:https://x.com/punish") == "无痕验证"


# ---------- detect_captcha 集成测试（fixture 页面） ----------

def test_detect_captcha_hit():
    async def scenario():
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.set_content('<div id="nc_1_wrapper">滑块</div>')
            result = await detect_captcha(page)
            await browser.close()
            return result

    assert asyncio.run(scenario()) == "滑块验证"


def test_detect_captcha_hit_fixed_position():
    # position:fixed 元素 offsetParent 恒为 null，需靠 getBoundingClientRect 兜底
    async def scenario():
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.set_content('<div id="nc_1_wrapper" style="position:fixed">滑块</div>')
            result = await detect_captcha(page)
            await browser.close()
            return result

    assert asyncio.run(scenario()) == "滑块验证"


def test_detect_captcha_miss():
    async def scenario():
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.set_content("<div>普通页面</div>")
            result = await detect_captcha(page)
            await browser.close()
            return result

    assert asyncio.run(scenario()) is None


# ---------- wait_manual_captcha：连续两次干净检测才判解除 ----------

def _dummy_log():
    lines = []

    def log(level, msg):
        lines.append((level, msg))

    return log, lines


def test_wait_manual_captcha_requires_two_clean_detections():
    # 序列 [None, 命中, None, None]：第 2 次命中清零连击，不提前返回；
    # 第 3、4 次连续干净后才判解除 → 共调用 4 次。
    log, lines = _dummy_log()
    det = AsyncMock(side_effect=[None, "滑块验证", None, None])
    with patch("app.captcha.detect_captcha", new=det):
        ok = asyncio.run(wait_manual_captcha(None, threading.Event(), log, max_wait_seconds=10))
    assert ok is True
    assert det.await_count == 4
    assert any("验证码已通过" in m for _, m in lines)


def test_wait_manual_captcha_two_clean_returns_after_2_calls():
    log, lines = _dummy_log()
    det = AsyncMock(side_effect=[None, None])
    with patch("app.captcha.detect_captcha", new=det):
        ok = asyncio.run(wait_manual_captcha(None, threading.Event(), log, max_wait_seconds=10))
    assert ok is True
    assert det.await_count == 2


def test_wait_manual_captcha_stop_event_returns_false():
    log, lines = _dummy_log()
    stop = threading.Event()
    stop.set()
    det = AsyncMock(side_effect=[None, None])
    with patch("app.captcha.detect_captcha", new=det):
        ok = asyncio.run(wait_manual_captcha(None, stop, log, max_wait_seconds=10))
    assert ok is False
    assert det.await_count == 0
