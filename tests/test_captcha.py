import asyncio
import threading

import pytest
from playwright.async_api import async_playwright

from app.captcha import describe_captcha, detect_captcha


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
