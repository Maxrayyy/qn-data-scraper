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
