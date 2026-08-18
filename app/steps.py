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
from urllib.parse import urlparse

from playwright.async_api import BrowserContext, Locator, Page, TimeoutError as PWTimeout

from .captcha import detect_captcha, wait_manual_captcha
from .config import AppConfig
from .scraper import (
    EXTRACT_JS,
    ProductItem,
    normalize_image_url,
    resolve_product_id,
)

# ============================ 可调参数 ============================
CATEGORY_NAME = "猫笼子/猫别墅"        # ★ 要分析的类目名
MAX_RETRIES = 2                          # 每步失败自动重试次数
CAPTCHA_MAX_WAIT_SECONDS = 600           # 验证码最长人工等待时间（秒）
SMS_VERIFY_MAX_WAIT_SECONDS = 300        # 短信验证身份最长人工等待时间（秒）
LOGIN_IFRAME = "#alibaba-login-box"   # ★ 登录表单所在 iframe（淘宝 havana 登录框，改版时检查）
LOGIN_SUCCESS_DOMAINS = ["qn.taobao.com"]      # 登录成功判据一：URL 域名（netloc 匹配）
LOGIN_SUCCESS_TEXTS = ["工作台"]               # 登录成功判据二：页面出现标志文字
LOGIN_FAIL_TEXTS = ["密码错误", "账号或密码不正确", "登录名不存在", "验证失败"]

# ============================ 元素定位器 ============================
# 每个键对应一组候选定位器，按顺序尝试，取第一个"可见"的元素。
STEP_LOCATORS: dict[str, list[str]] = {
    # ---- 登录页（位于跨域 iframe 内，经 frame_locator 使用）----
    "密码登录页签": [
        "a.password-login-tab-item",
        "//a[normalize-space()='密码登录']",
    ],
    "账号输入框": [
        "#fm-login-id",
        "input[name='fm-login-id']",
        "input[placeholder*='账号名']",
        "input[placeholder*='会员名']",
    ],
    "密码输入框": [
        "#fm-login-password",
        "input[name='fm-login-password']",
        "input[placeholder*='登录密码']",
        "input[type='password']",
    ],
    "登录按钮": [
        "button.fm-submit",
        "button:has-text('登录')",
        "#login-form button[type='submit']",
        ".fm-button",
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
    rows_sink: list | None = None    # 抓到的数据实时追加，供中途停止时尽力导出

    def emit(self, level: str, msg: str) -> None:
        self.log(level, msg)


@dataclass
class FlowResult:
    rows: list[tuple[ProductItem, Path | None]] = field(default_factory=list)


# ============================ 步骤框架 ============================

def _is_login_success_url(url: str) -> bool:
    """登录成功判据一：URL 的域名（netloc）包含目标域名。

    只匹配 netloc，不匹配查询参数——登录页 URL 的 redirect_url 参数里
    可能含有 qn.taobao.com，子串匹配会造成"未登录却判定成功"的假阳性。
    """
    netloc = urlparse(url).netloc.lower()
    return any(d in netloc for d in LOGIN_SUCCESS_DOMAINS)


async def _detect_sms_verify(page: Page) -> bool:
    """检测手机短信验证身份界面（havana identity_verify：验证码输入框/获取验证码按钮）。"""
    for frame in page.frames:
        try:
            loc = frame.locator("#J_Checkcode, #J_GetCode, input[placeholder='6位数字']")
            n = await loc.count()
            for i in range(min(n, 3)):
                if await loc.nth(i).is_visible():
                    return True
        except Exception:
            continue
    return False


async def _wait_sms_verify(page: Page, ctx: StepsContext) -> bool:
    """短信验证身份：自动点击『点击获取验证码』，等待人工输入 6 位数字验证码并确认。

    返回 True=验证界面已结束（成功跳转或退回登录页，由第 3 步判定），False=超时或被停止。
    """
    ctx.emit(
        "warn",
        "检测到手机短信验证身份：已自动点击『点击获取验证码』，"
        "请在浏览器窗口输入收到的 6 位数字验证码并点『确定』，工具等待中…",
    )
    # 自动点击"点击获取验证码"按钮
    for frame in page.frames:
        try:
            btn = frame.locator("#J_GetCode")
            if await btn.count() > 0 and await btn.nth(0).is_visible():
                await btn.nth(0).click()
                break
        except Exception:
            continue
    waited = 0
    while waited < SMS_VERIFY_MAX_WAIT_SECONDS:
        _check_stop(ctx)
        if _is_login_success_url(page.url):
            ctx.emit("success", "短信验证通过，继续登录流程。")
            return True
        if not await _detect_sms_verify(page):
            # 验证界面消失：可能已完成或退回登录页，交给第 3 步判定
            ctx.emit("info", "验证码输入界面已关闭，继续检查登录状态…")
            return True
        await asyncio.sleep(1)
        waited += 1
        if waited % 15 == 0:
            ctx.emit("info", f"仍在等待短信验证输入…（已等待 {waited} 秒，最长 {SMS_VERIFY_MAX_WAIT_SECONDS} 秒）")
    return False


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
    """执行一个内置步骤：停止检查 → 执行（失败自动重试）→ 验证码检查 → 中文日志。

    若动作在所有尝试后仍未成功、随后验证码被人工解除，会重新执行一次该步骤；
    重跑仍失败（或始终无验证码且动作失败）时抛 StepFailed。
    """
    ctx.emit("info", f"【第 {step_no} 步】{name}…")
    _check_stop(ctx)
    result = None
    succeeded = False
    last_err: Exception | None = None
    for attempt in range(1, ctx.max_retries + 2):  # 1 次正式 + N 次重试
        _check_stop(ctx)
        try:
            result = await action()
            succeeded = True
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
    # 每步之后统一验证码检查
    hit = await detect_captcha(page)
    if hit:
        ctx.emit("warn", f"检测到{hit}，请人工处理…")
        ok = await wait_manual_captcha(page, ctx.stop_event, ctx.log, CAPTCHA_MAX_WAIT_SECONDS)
        if not ok:
            if ctx.stop_event.is_set():
                raise TaskStopped()
            raise StepFailed(f"验证码等待超时（{CAPTCHA_MAX_WAIT_SECONDS} 秒未处理），任务终止")
        if not succeeded:
            # 验证码可能一直遮住页面导致动作未成功：解除后重新执行一次
            ctx.emit("info", f"验证码已解除，重新执行第 {step_no} 步『{name}』…")
            _check_stop(ctx)
            try:
                result = await action()
                succeeded = True
            except TaskStopped:
                raise
            except Exception as e:
                last_err = e
    if not succeeded:
        raise StepFailed(f"第 {step_no} 步『{name}』失败：{last_err}")
    ctx.emit("success", f"第 {step_no} 步『{name}』完成。")
    return result


async def _locate_first(root, key: str) -> Locator | None:
    """按 STEP_LOCATORS[key] 候选顺序，返回第一个可见元素；全部未命中返回 None。

    root 可为 Page 或 FrameLocator（登录表单位于跨域 iframe 内，二者均支持 .locator()）。
    """
    for sel in STEP_LOCATORS.get(key, []):
        try:
            loc = root.locator(sel)
            n = await loc.count()
            for i in range(min(n, 20)):
                cand = loc.nth(i)
                if await cand.is_visible():
                    return cand
        except Exception:
            continue
    return None


async def _check_remember_password(frame) -> None:
    """勾选登录框内"记住密码"复选框（尽力而为：让淘宝信任本设备，减少短信验证）。"""
    try:
        box = frame.locator("input[type='checkbox']")
        n = await box.count()
        for i in range(min(n, 5)):
            el = box.nth(i)
            try:
                if await el.is_visible() and not await el.is_checked():
                    await el.check()
                    return
            except Exception:
                try:
                    await el.click()
                    return
                except Exception:
                    continue
        # 回退：点击含"记住"文字的标签
        for sel in ("label:has-text('记住')", "[class*='remember']"):
            try:
                el = frame.locator(sel).first
                if await el.count() > 0 and await el.is_visible():
                    await el.click()
                    return
            except Exception:
                continue
    except Exception:
        pass


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


async def _dismiss_popups(page: Page, ctx: StepsContext) -> int:
    """关闭遮挡操作的弹窗（如登录后的安全检测弹窗）：点可见弹窗的关闭按钮，失败按 Esc。

    最多处理 3 个弹窗，返回关闭数量。不会影响第 9 步的『商品发现』弹窗
    （该步执行时弹窗已由步骤自身关闭）。
    """
    closed = 0
    for _ in range(3):
        dialog = None
        for sel in STEP_LOCATORS["弹窗容器"]:
            try:
                loc = page.locator(sel)
                n = await loc.count()
                for i in range(n - 1, -1, -1):
                    if await loc.nth(i).is_visible():
                        dialog = loc.nth(i)
                        break
            except Exception:
                continue
            if dialog:
                break
        if dialog is None:
            break
        done = False
        for sel in STEP_LOCATORS["弹窗关闭按钮"]:
            try:
                loc = page.locator(sel)
                n = await loc.count()
                for i in range(n - 1, -1, -1):
                    if await loc.nth(i).is_visible():
                        await loc.nth(i).click()
                        closed += 1
                        done = True
                        break
            except Exception:
                continue
            if done:
                break
        if not done:
            try:
                await page.keyboard.press("Escape")
                closed += 1
            except Exception:
                break
        await asyncio.sleep(0.5)
    if closed:
        ctx.emit("info", f"已关闭 {closed} 个遮挡弹窗。")
    return closed


async def _click_nav(page: Page, ctx: StepsContext, key: str, name: str) -> None:
    """导航点击：先关闭可能遮挡的弹窗，再点击目标元素。"""
    await _dismiss_popups(page, ctx)
    await _click_first(page, key, name)


# ============================ 内置步骤 1-9 ============================

async def run_builtin_flow(page: Page, cfg: AppConfig, ctx: StepsContext) -> FlowResult:
    """主流程：依次执行 9 个内置步骤。修改点击顺序改这里。"""
    result = FlowResult()
    await _run_step(ctx, 1, "打开登录页", lambda: _step_open_login(page, cfg, ctx), page)
    await _run_step(ctx, 2, "填写账号密码并登录", lambda: _step_login(page, cfg, ctx), page)
    await _run_step(ctx, 3, "等待登录成功跳转工作台", lambda: _step_wait_login(page, ctx), page)
    await _run_step(ctx, 4, "点击左侧菜单「数据」", lambda: _click_nav(page, ctx, "左侧数据菜单", "数据"), page)
    await _run_step(ctx, 5, "点击上方页签「市场」", lambda: _click_nav(page, ctx, "上方市场页签", "市场"), page)
    await _run_step(ctx, 6, "点击左侧菜单「类目洞察」", lambda: _click_nav(page, ctx, "左侧类目洞察菜单", "类目洞察"), page)
    await _run_step(ctx, 7, "点击「价格分析」", lambda: _click_nav(page, ctx, "价格分析页签", "价格分析"), page)
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
    # 登录表单在跨域 iframe 内（淘宝 havana 登录框），先等 iframe 出现
    try:
        await page.wait_for_selector(LOGIN_IFRAME, timeout=max(ctx.timeout_ms, 15000))
    except PWTimeout:
        raise StepFailed("找不到登录框（LOGIN_IFRAME），登录页可能已改版")
    frame = page.frame_locator(LOGIN_IFRAME)
    # 条件等待：账号输入框渲染完成（替代固定延时）
    try:
        await frame.locator("#fm-login-id").wait_for(state="visible", timeout=max(ctx.timeout_ms, 15000))
    except PWTimeout:
        raise StepFailed("登录框已出现，但账号输入框一直未渲染（可能网络慢或被风控拦截）")
    # 默认已是密码登录视图，点击"密码登录"页签仅为兜底
    try:
        tab = await _locate_first(frame, "密码登录页签")
        if tab:
            await tab.click()
            await asyncio.sleep(0.5)
    except Exception:
        pass
    for _ in range(3):  # 最多尝试 3 轮（验证码打断会消耗轮次）
        _check_stop(ctx)
        for key, value in (("账号输入框", cfg.username), ("密码输入框", cfg.password)):
            field = await _locate_first(frame, key)
            if field is None:
                raise StepFailed(f"找不到{'账号' if '账号' in key else '密码'}输入框，登录页可能已改版")
            await field.fill(value)
        # 勾选"记住密码"（可让淘宝信任本设备，减少后续短信验证），尽力而为
        await _check_remember_password(frame)
        login_btn = await _locate_first(frame, "登录按钮")
        if login_btn is None:
            raise StepFailed("找不到登录按钮，登录页可能已改版")
        await login_btn.click()
        await asyncio.sleep(2)
        hit = await detect_captcha(page)
        if hit:
            ctx.emit("warn", f"登录时出现{hit}！请在浏览器窗口中手动完成验证…")
            ok = await wait_manual_captcha(page, ctx.stop_event, ctx.log, CAPTCHA_MAX_WAIT_SECONDS)
            if not ok:
                if ctx.stop_event.is_set():
                    raise TaskStopped()
                raise StepFailed("验证码等待超时，登录失败")
            # 验证通过后循环重填重登
            continue
        # 手机短信验证身份步骤（密码登录后淘宝要求验证手机短信）
        if await _detect_sms_verify(page):
            ok = await _wait_sms_verify(page, ctx)
            if not ok:
                if ctx.stop_event.is_set():
                    raise TaskStopped()
                raise StepFailed("短信验证未完成（等待超时），登录失败")
            return  # 验证界面已结束，交给第 3 步判定登录结果
        return  # 交给第 3 步验证是否真正登录成功
    raise StepFailed("多次尝试后仍未完成登录（可能验证码未处理或页面改版）")


# ---- 第 3 步：等待登录成功 ----

async def _step_wait_login(page: Page, ctx: StepsContext) -> None:
    deadline = asyncio.get_event_loop().time() + max(ctx.timeout_ms / 1000 * 3, 90)
    while asyncio.get_event_loop().time() < deadline:
        _check_stop(ctx)
        if _is_login_success_url(page.url):
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
    await _dismiss_popups(page, ctx)
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
        if ctx.rows_sink is not None:
            ctx.rows_sink.extend(items)
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
            product_id=resolve_product_id(
                d.get("idText", ""), d.get("href", ""), normalize_image_url(d.get("img", ""))
            ),
            orders=d.get("orders", ""),
            price=d.get("price", ""),
        )
        if not item.product_id:
            ctx.emit("warn", f"商品『{item.name[:20]}』未解析到商品id，已留空。")
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
