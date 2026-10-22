"""Check a --js-plots report offline, including viewer and browser fallbacks.

python tests/jsplot_browser.py report.html [--chromium /path/to/chrome]
"""
import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright


def check(browser, path, fallback=False):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    if fallback:
        context.add_init_script("delete window.IntersectionObserver; delete window.ResizeObserver;")
    page = context.new_page()
    errors, requests = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda request: requests.append(request.url))
    page.goto(path.as_uri())
    page.wait_for_selector('canvas[data-rendered="true"]', timeout=60000)
    page.locator('[data-image-index]').first.click()
    page.wait_for_selector('#viewer-content canvas[data-rendered="true"]', timeout=60000)
    assert page.locator('#viewer-original').is_hidden()
    if page.locator('#viewer-next').is_enabled():
        page.locator('#viewer-next').click()
        page.wait_for_selector('#viewer-content canvas[data-rendered="true"]', timeout=60000)
    page.locator('#viewer-close').click()
    page.locator('[data-view="overview"]').click()
    assert page.locator('#plot-grid canvas').count() == 0
    page.locator('[data-view="plots"]').click()
    title = page.locator('#plot-grid h2').first.inner_text()
    page.locator('#title-search').fill(title)
    page.wait_for_selector('canvas[data-rendered="true"]', timeout=60000)
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(500)
    assert not page.locator('canvas[data-error]').count()
    assert not errors, errors
    assert requests == [path.as_uri()], requests
    context.close()


def check_unsupported(browser, path):
    context = browser.new_context()
    context.add_init_script('delete window.DecompressionStream;')
    page = context.new_page()
    page.goto(path.as_uri())
    page.wait_for_selector('canvas[data-error]', timeout=60000)
    assert "default SVG report" in page.locator('canvas[data-error]').first.get_attribute('data-error')
    context.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--chromium')
    args = parser.parse_args()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.chromium)
        check(browser, args.report.resolve())
        check(browser, args.report.resolve(), fallback=True)
        check_unsupported(browser, args.report.resolve())
        browser.close()
    print("JS report browser checks passed")
