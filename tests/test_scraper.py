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
