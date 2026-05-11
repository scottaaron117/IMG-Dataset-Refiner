"""Browser smoke test for IMG Dataset Refiner.

What it covers (regression-tests the Phase 2 JS-bridge fixes):
- Page loads, custom_js injects, all expected elem_ids are present.
- Dataset loads from disk into the gallery.
- Single click on a thumbnail syncs to hidden_sync_input and applies the
  orange .custom-selected outline (this used to silently no-op because
  Gradio 5 renders thumbnails as <a class="thumbnail-item">, not <button>).
- Shift-click range-selects multiple thumbnails.
- Ctrl/Cmd-click toggles individual thumbnails.
- The currently-selected thumbnail's caption loads into the editor.
- Caption autocomplete dropdown appears after typing 2+ chars.
- All declared tabs are present.

How to run locally:

    # one-time setup
    pip install -e .
    pip install playwright
    playwright install chromium

    # in one shell
    python lora_manager.py

    # in another shell
    python tests/test_smoke.py

Or run under pytest (the file is also pytest-compatible).

Env vars:
    SMOKE_URL          (default: http://127.0.0.1:7860/)
    SMOKE_DATASET      (default: ./dataset/(datasets exemple) - Dall-e style)
    SMOKE_CHROME       (default: auto via Playwright; set to a full path to override)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

URL = os.environ.get("SMOKE_URL", "http://127.0.0.1:7860/")
DEFAULT_DATASET = REPO_ROOT / "dataset" / "(datasets exemple) - Dall-e style"
DATASET = os.environ.get("SMOKE_DATASET", str(DEFAULT_DATASET))
EXPLICIT_CHROME = os.environ.get("SMOKE_CHROME")


def _launch_browser(p):
    kwargs = dict(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    if EXPLICIT_CHROME:
        kwargs["executable_path"] = EXPLICIT_CHROME
    return p.chromium.launch(**kwargs)


def run_smoke():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed. Run: pip install playwright && playwright install chromium")
        return 2

    results: list[tuple[str, bool, str]] = []

    def step(name, ok, detail=""):
        results.append((name, ok, detail))
        tag = "OK  " if ok else "FAIL"
        print(f"[{tag}] {name}" + (f" -- {detail}" if detail else ""))

    with sync_playwright() as p:
        try:
            browser = _launch_browser(p)
        except Exception as e:
            print(f"Could not launch Chromium: {e}")
            print("On most systems: `playwright install chromium`")
            return 2

        ctx = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = ctx.new_page()

        # Google Fonts can fail in restricted networks; ignore those console errors.
        app_console_errors: list[tuple[str, str]] = []

        def _on_console(m):
            txt = m.text
            if "ERR_CERT_AUTHORITY_INVALID" in txt or "fonts.googleapis.com" in txt:
                return
            if m.type in ("error", "warning"):
                app_console_errors.append((m.type, txt))

        page.on("console", _on_console)
        page.on("pageerror", lambda e: app_console_errors.append(("pageerror", str(e))))

        page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("#main_gallery", timeout=15000)
        page.wait_for_timeout(2000)
        step("page loaded", True)

        for eid in [
            "main_gallery", "viewer_caption_area", "hidden_sync_input",
            "multi_cb", "save_single_btn", "prev_btn", "next_btn",
            "dataset_dir_input", "load_btn", "tracked_words_input",
        ]:
            step(f"#{eid} present", page.locator(f"#{eid}").count() > 0)

        step("custom_js injected", page.evaluate("() => !!window.__DIES_INJECTED"))

        # Load the dataset
        page.locator("#dataset_dir_input textarea, #dataset_dir_input input").first.fill(DATASET)
        page.locator("#load_btn").click()
        page.wait_for_timeout(8000)

        thumbs = page.locator("#main_gallery .thumbnail-item")
        n_thumbs = thumbs.count()
        step("gallery rendered thumbnails", n_thumbs > 0, f"count={n_thumbs}")

        if n_thumbs > 0:
            thumbs.first.click()
            page.wait_for_timeout(600)
            sync_val = page.evaluate(
                "() => { const w = document.getElementById('hidden_sync_input');"
                " const inp = w && w.querySelector('textarea, input'); return inp ? inp.value : null; }"
            )
            step(
                "single-click syncs hidden_sync_input",
                bool(sync_val) and sync_val != "{}" and '"selected"' in sync_val,
                f"val={sync_val[:120] if sync_val else 'None'}",
            )
            step(
                "single-click sets .custom-selected",
                thumbs.first.evaluate("el => el.classList.contains('custom-selected')"),
            )

            if n_thumbs >= 3:
                thumbs.nth(2).click(modifiers=["Shift"])
                page.wait_for_timeout(400)
                n_after_shift = page.locator("#main_gallery .thumbnail-item.custom-selected").count()
                step("shift-click range-select", n_after_shift >= 3, f"selected={n_after_shift}")

                thumbs.nth(1).click(modifiers=["ControlOrMeta"])
                page.wait_for_timeout(300)
                n_after_ctrl = page.locator("#main_gallery .thumbnail-item.custom-selected").count()
                step(
                    "ctrl-click toggles selection",
                    n_after_ctrl < n_after_shift,
                    f"before={n_after_shift} after={n_after_ctrl}",
                )

            cap = page.locator("#viewer_caption_area textarea").first
            step("caption populated after click", bool(cap.input_value().strip()))

            cap.click()
            cap.press("End")
            cap.type(", styl")
            page.wait_for_timeout(500)
            n_ac = page.locator("#autocomplete-list div").count()
            step("autocomplete dropdown appears", n_ac > 0, f"options={n_ac}")
            for _ in range(6):
                cap.press("Backspace")

        tabs = page.evaluate(
            "() => Array.from(document.querySelectorAll('button[role=\"tab\"], [role=\"tab\"]'))"
            ".map(el => (el.textContent || '').trim())"
        )
        step("tabs present", len(tabs) > 0, f"count={len(tabs)} labels={tabs[:8]}")

        step(
            "no app-relevant console errors",
            len(app_console_errors) == 0,
            str(app_console_errors[:3]) if app_console_errors else "",
        )

        page.screenshot(path=str(REPO_ROOT / "tests" / "smoke_screenshot.png"), full_page=False)
        browser.close()

    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{len(results) - failed} / {len(results)} steps passed")
    for name, ok, detail in results:
        if not ok:
            print(f"  FAIL: {name} -- {detail[:200]}")
    return failed


def test_smoke():
    """pytest entry point. Skips if the app isn't running."""
    import socket
    import urllib.parse

    try:
        import pytest
    except ImportError:
        pytest = None

    parsed = urllib.parse.urlparse(URL)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    try:
        sock.connect((parsed.hostname or "127.0.0.1", parsed.port or 80))
        sock.close()
    except OSError:
        if pytest is not None:
            pytest.skip(f"App not running at {URL}; start `python lora_manager.py` first.")
        return

    failed = run_smoke()
    assert failed == 0, f"{failed} smoke step(s) failed"


if __name__ == "__main__":
    sys.exit(run_smoke())
