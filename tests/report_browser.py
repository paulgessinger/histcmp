"""Check generated reports in Chromium, including file:// loading.

With Playwright and Chromium installed:
    python tests/report_browser.py /absolute/path/to/report.html
Use reports with more than 24 histograms, or empty reports.
"""

import argparse
import json
from pathlib import Path
import time
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright


def check_report(browser, path):
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    errors, requests = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda request: requests.append(request.url))
    started = time.perf_counter()
    page.goto(path.as_uri())
    metadata = json.loads(page.locator("#report-data").text_content())
    items, tags = metadata["items"], metadata["tags"]

    def results(expected):
        slots = page.locator("#plot-grid .plot-slot")
        expect(slots).to_have_count(len(expected))
        assert slots.evaluate_all("els => els.map(el => el.dataset.item)") == [i["id"] for i in expected]

    def wait_visible_images():
        page.wait_for_function("""() => [...document.querySelectorAll('#plot-grid img')]
            .filter(img => { const r = img.getBoundingClientRect(); return r.top < innerHeight && r.bottom > 0; })
            .every(img => img.complete && img.naturalWidth > 0)""")

    results(items)
    assert page.locator("[data-page], #status-filter select").count() == 0
    for value in ["", "failure", "success", "inconclusive"]:
        expect(page.locator(f'[data-status="{value}"]')).to_be_visible()
    if not items:
        expect(page.locator("#empty-results")).to_be_visible()
        assert not errors, errors
        context.close()
        return {"items": 0, "empty_state": "passed"}
    assert len(items) > 24
    page.wait_for_function("document.querySelector('#plot-grid img[src]')?.naturalWidth > 0")
    ready_seconds = time.perf_counter() - started
    initial_loaded = page.locator("#plot-grid img[src]").count()
    initial_cards = page.locator("#plot-grid .plot").count()
    assert 0 < initial_loaded < sum(1 for _ in items)
    assert 0 < initial_cards < 30
    wait_visible_images()
    page.screenshot(path=str(path.with_suffix(".desktop.png")))

    # Scrolling reaches previously unmounted cards and releases distant cards.
    first = items[0]["id"]
    page.locator(f"#{first} .check summary").first.click()
    page.locator('[data-status=""]').focus()
    middle = items[len(items) // 2]["id"]
    page.locator(f'[data-item="{middle}"]').evaluate("el => el.scrollIntoView({block: 'start'})")
    expect(page.locator(f"#{middle}")).to_be_visible()
    page.wait_for_function("id => document.querySelector(`#${id} img[src]`)?.naturalWidth > 0", arg=middle)
    expect(page.locator(f"#{first}")).to_have_count(0)
    assert page.locator("#plot-grid .plot").count() < 40
    page.locator(f'[data-item="{first}"]').evaluate("el => el.scrollIntoView({block: 'start'})")
    expect(page.locator(f"#{first} .check[open]")).to_have_count(1)

    # Every visible status button filters the full collection.
    for status in ["failure", "success", "inconclusive", ""]:
        page.locator(f'[data-status="{status}"]').click()
        results([item for item in items if not status or item["status"] == status])
        expect(page.locator(f'[data-status="{status}"]')).to_have_attribute("aria-pressed", "true")

    last = items[-1]
    query = last["title"].upper()
    matching = [item for item in items if query.lower() in item["title"].lower()]
    started = time.perf_counter()
    page.locator("#title-search").fill(query)
    results(matching)
    search_seconds = time.perf_counter() - started
    assert parse_qs(urlsplit(page.url).query)["q"] == [query]
    page.reload()
    expect(page.locator("#title-search")).to_have_value(query)
    results(matching)
    page.locator("#title-search").fill("no-such-histogram-7f8b907e")
    expect(page.locator("#empty-results")).to_be_visible()
    results([])
    page.locator("#clear-filters").click()
    results(items)

    if len(tags) >= 2:
        pair = next((item["tags"][:2] for item in items if len(item["tags"]) >= 2), tags[:2])
        for name in pair:
            page.locator(f'#tag-filter input[value="tag-{tags.index(name)}"]').check()
        union = [item for item in items if any(name in item["tags"] for name in pair)]
        results(union)
        page.locator('#tag-filter input[value="untagged"]').check()
        union = [item for item in items if not item["tags"] or any(name in item["tags"] for name in pair)]
        results(union)
        target = union[-1]
        page.locator(f'[data-status="{target["status"]}"]').click()
        page.locator("#title-search").fill(target["title"])
        expected = [item for item in union if item["status"] == target["status"] and target["title"].lower() in item["title"].lower()]
        results(expected)
        saved_url = page.url
        params = parse_qs(urlsplit(saved_url).query)
        assert set(params["tag"]) == set(pair)
        assert params["untagged"] == ["1"]
        assert params["status"] == [target["status"]]
        page.reload()
        results(expected)
        expect(page.locator("#title-search")).to_have_value(target["title"])
        for name in pair:
            expect(page.locator(f'#tag-filter input[value="tag-{tags.index(name)}"]')).to_be_checked()
        expect(page.locator('#tag-filter input[value="untagged"]')).to_be_checked()
        expect(page.locator(f'[data-status="{target["status"]}"]')).to_have_attribute("aria-pressed", "true")
        page.goto(saved_url + "#" + target["id"])
        expect(page.locator(f'#{target["id"]}')).to_be_visible()
        results(expected)

    page.locator("#clear-filters").click()
    results(items)
    assert not urlsplit(page.url).query
    page.evaluate("window.scrollTo(0, 0)")
    chip = page.locator("#plot-grid [data-filter-tag]").first
    expect(chip).to_be_visible()
    value = chip.get_attribute("data-filter-tag")
    chip.click()
    expect(page.locator(f'#tag-filter input[value="{value}"]')).to_be_checked()
    expect(page.locator(f'#plot-grid [data-filter-tag="{value}"]').first).to_have_attribute("aria-pressed", "true")
    page.locator(f'#plot-grid [data-filter-tag="{value}"]').first.click()
    expect(page.locator(f'#tag-filter input[value="{value}"]')).not_to_be_checked()

    page.evaluate("(id) => { location.hash = id; }", last["id"])
    expect(page.locator(f"#{last['id']}")).to_be_visible()
    page.reload()
    expect(page.locator(f"#{last['id']}")).to_be_visible()
    assert page.locator("#plot-grid .plot").count() < 40
    page.locator("#clear-filters").click()
    page.set_viewport_size({"width": 390, "height": 844})
    page.evaluate("window.scrollTo(0, 0)")
    expect(page.locator(f"#{first}")).to_be_attached()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.locator("#plot-grid").evaluate("el => getComputedStyle(el).gridTemplateColumns.split(' ').length") == 1
    wait_visible_images()
    page.screenshot(path=str(path.with_suffix(".mobile.png")))
    assert not errors, errors
    assert not any(url.startswith(("http:", "https:")) for url in requests), requests
    context.close()

    # Compatibility fallback still renders when IntersectionObserver is absent.
    if len(items) < 1000:
        context = browser.new_context()
        context.add_init_script("delete window.IntersectionObserver")
        page = context.new_page()
        page.goto(path.as_uri())
        expect(page.locator("#plot-grid .plot")).to_have_count(len(items))
        page.wait_for_function("document.querySelector('#plot-grid img[src]')?.naturalWidth > 0")
        context.close()
    return {"items": len(items), "ready_seconds": ready_seconds,
            "search_seconds_including_debounce": search_seconds,
            "initial_loaded_images": initial_loaded, "initial_mounted_cards": initial_cards,
            "external_requests": 0, "url_restoration": "passed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, nargs="+")
    parser.add_argument("--browser", help="Optional path to an existing Chromium executable")
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.browser)
        results = {str(path): check_report(browser, path.resolve()) for path in args.report}
        browser.close()
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
