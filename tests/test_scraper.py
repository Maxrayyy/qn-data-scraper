from playwright.sync_api import sync_playwright

from app.scraper import (
    EXTRACT_JS,
    extract_product_id,
    normalize_image_url,
    resolve_product_id,
)


# ---------- 纯函数 ----------

def test_extract_product_id_query():
    assert extract_product_id("https://item.taobao.com/item.htm?id=123456&spm=x") == "123456"


def test_extract_product_id_path():
    assert extract_product_id("https://detail.tmall.com/item/778899.htm") == "778899"


def test_extract_product_id_none():
    assert extract_product_id("https://example.com/foo/bar") == ""


def test_resolve_product_id_fallback_to_image():
    # 无可见数字、href 无 id，图片 URL 有 id → 回退取图片 id
    assert (
        resolve_product_id(
            "", "https://item.taobao.com/item.htm", "https://img.alicdn.com/abc?id=777777"
        )
        == "777777"
    )


def test_resolve_product_id_both_missing():
    assert (
        resolve_product_id("", "https://example.com/x", "https://img.alicdn.com/y.jpg")
        == ""
    )


def test_resolve_product_id_href_wins():
    # 无可见数字、href 有 id 时优先于图片 URL
    assert (
        resolve_product_id(
            "",
            "https://item.taobao.com/item.htm?id=555555",
            "https://img.alicdn.com/z.jpg?id=999999",
        )
        == "555555"
    )


def test_resolve_product_id_prefers_id_text():
    # 名字下方可见数字 id 优先于链接/图片中的不同 id（含首尾空白去除）
    assert (
        resolve_product_id(
            "  1067290266725  ",
            "https://item.taobao.com/item.htm?id=111111",
            "https://img.alicdn.com/z.jpg?id=999999",
        )
        == "1067290266725"
    )


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
    <div class="cell">
      <a href="https://item.taobao.com/item.htm?id=111111">
        <img src="//img.alicdn.com/a.jpg"><span>猫别墅A</span>
      </a><span class="id">1067290266725</span>
    </div>
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
  <div class="row"><div class="cell">
    <a href="https://item.taobao.com/item.htm?id=333333">
      <img src="//img.alicdn.com/c.jpg"><span>猫粮碗C</span>
    </a><span class="id">1067290266726</span></div><span>20</span><span>¥50</span></div>
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
    assert data[0]["idText"] == "1067290266725"
    assert data[1]["name"] == "猫笼子B"
    assert data[1]["idText"] == ""


def test_extract_js_no_header_fallback():
    data = _extract(FIXTURE_NO_HEADER)
    assert len(data) == 1
    assert data[0]["href"].endswith("id=333333")
    assert data[0]["orders"] == "20"
    assert data[0]["price"] == "¥50"
    assert data[0]["idText"] == "1067290266726"
