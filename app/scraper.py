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
