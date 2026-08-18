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
