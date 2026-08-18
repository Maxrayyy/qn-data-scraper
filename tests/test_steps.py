import asyncio
import threading
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from playwright.async_api import async_playwright

from app.steps import (
    StepFailed,
    StepsContext,
    TaskStopped,
    _locate_first,
    _run_step,
)


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


@pytest.mark.asyncio
async def test_run_step_captcha_resolved_reruns_action():
    # max_retries=0：重试循环只跑 1 次（失败），成功只能来自验证码解除后的重跑
    ctx, log = make_ctx(max_retries=0)
    page = AsyncMock()
    calls = [0]

    async def flaky():
        calls[0] += 1
        if calls[0] == 1:
            raise RuntimeError("第一次失败")
        return "ok2"

    with patch("app.steps.detect_captcha", new=AsyncMock(return_value="滑块验证")), \
         patch("app.steps.wait_manual_captcha", new=AsyncMock(return_value=True)):
        result = await _run_step(ctx, 6, "验证码重跑步骤", flaky, page)
    assert result == "ok2"
    assert calls[0] == 2
    assert any("重新执行" in m for _, m in log.lines)


def test_locate_first_supports_frame_locator():
    # 登录表单位于跨域 iframe（如淘宝 #alibaba-login-box）内，
    # _locate_first 需支持传入 FrameLocator（root 鸭子类型：均有 .locator() 方法）
    async def scenario():
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.set_content(
                '<iframe id="loginbox" srcdoc=\'<input id="fm-login-id">\'></iframe>'
            )
            frame = page.frame_locator("#loginbox")
            el = await _locate_first(frame, "账号输入框")
            assert el is not None
            assert await el.get_attribute("id") == "fm-login-id"
            await browser.close()

    asyncio.run(scenario())


@pytest.mark.asyncio
async def test_run_step_captcha_resolved_rerun_still_fails():
    ctx, log = make_ctx(max_retries=0)
    page = AsyncMock()
    calls = [0]

    async def always_fail():
        calls[0] += 1
        raise RuntimeError("一直失败")

    with patch("app.steps.detect_captcha", new=AsyncMock(return_value="滑块验证")), \
         patch("app.steps.wait_manual_captcha", new=AsyncMock(return_value=True)):
        with pytest.raises(StepFailed, match="验证码重跑步骤"):
            await _run_step(ctx, 7, "验证码重跑步骤", always_fail, page)
    assert calls[0] == 2
    assert any("重新执行" in m for _, m in log.lines)
