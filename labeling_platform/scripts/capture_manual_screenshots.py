"""Capture simplified User Manual screenshots from a running Streamlit app.

Usage (from labeling_platform/):
  1. streamlit run app.py --server.port 8501
  2. python scripts/capture_manual_screenshots.py

Requires: playwright (`pip install playwright` then `playwright install chromium`)
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from playwright.sync_api import Page, sync_playwright
except ImportError:
    print("Install playwright: pip install playwright && playwright install chromium")
    sys.exit(1)

APP_URL = "http://localhost:8501"
OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "manual_images"
USERNAME = "manualdemo"
PASSWORD = "manual123"
VIEWPORT = {"width": 1440, "height": 900}


def scroll_main_top(page: Page) -> None:
    page.evaluate(
        """() => {
            const main = document.querySelector('[data-testid="stMainBlockContainer"]');
            if (main) main.scrollTop = 0;
            window.scrollTo(0, 0);
        }"""
    )
    page.wait_for_timeout(800)


def nudge_scroller(page: Page, delta_px: int) -> None:
    page.evaluate(
        """(delta) => {
            const scroller =
              document.querySelector('[data-testid="stMainBlockContainer"]') ||
              document.querySelector('section.main');
            if (scroller) scroller.scrollTop += delta;
        }""",
        delta_px,
    )
    page.wait_for_timeout(500)


def scroll_to_text(
    page: Page,
    pattern: str,
    *,
    exact: bool = False,
    last: bool = False,
    top_offset_px: int = 40,
) -> None:
    loc = page.get_by_text(pattern, exact=exact).last if last else page.get_by_text(pattern, exact=exact).first
    loc.wait_for(state="visible", timeout=30000)
    loc.scroll_into_view_if_needed()
    page.wait_for_timeout(400)
    page.evaluate(
        """({ el, topOffset }) => {
            if (!el) return;
            const candidates = [
              document.querySelector('[data-testid="stMainBlockContainer"]'),
              document.querySelector('[data-testid="stAppViewContainer"]'),
              document.querySelector('section.main'),
              document.scrollingElement
            ].filter(Boolean);
            for (const scroller of candidates) {
                const before = scroller.scrollTop || window.scrollY || 0;
                const sRect = scroller.getBoundingClientRect ? scroller.getBoundingClientRect() : { top: 0 };
                const eRect = el.getBoundingClientRect();
                scroller.scrollTop += eRect.top - sRect.top - topOffset;
                if (Math.abs((scroller.scrollTop || 0) - before) > 1) break;
            }
        }""",
        {"el": loc.element_handle(), "topOffset": top_offset_px},
    )
    page.wait_for_timeout(900)


def assert_visible(page: Page, pattern: str, *, exact: bool = False, last: bool = False) -> None:
    loc = page.get_by_text(pattern, exact=exact).last if last else page.get_by_text(pattern, exact=exact).first
    if not loc.is_visible():
        raise RuntimeError(f"Expected visible text not found in viewport: {pattern!r}")


def sign_in(page: Page) -> None:
    page.goto(APP_URL, wait_until="networkidle")
    page.wait_for_timeout(2000)
    page.get_by_role("textbox", name="Username").fill(USERNAME)
    page.get_by_role("textbox", name="Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign In").click()
    page.wait_for_timeout(5000)
    page.get_by_text("Answer (main text to code)", exact=False).first.wait_for(
        state="visible", timeout=30000
    )
    page.get_by_text("CGM Contingency Speech Scoring", exact=False).first.wait_for(
        state="visible", timeout=30000
    )


def select_primary(page: Page, title: str) -> None:
    option = page.locator("label").filter(has_text=title).first
    option.wait_for(state="visible", timeout=30000)
    option.click()
    page.wait_for_timeout(1000)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 560})
        sign_in(page)

        # Simple Figure 1 - fixed Question/Answer panel and navigation.
        scroll_main_top(page)
        page.screenshot(path=str(OUT_DIR / "simple-01-overview-qa-navigation.png"))
        page.set_viewport_size(VIEWPORT)

        # Simple Figure 2 - Primary Hierarchy starts blank on a new Answer item.
        scroll_main_top(page)
        scroll_to_text(page, "Primary Hierarchy", exact=False, top_offset_px=150)
        assert_visible(page, "Select one Primary Hierarchy level for the Answer", exact=False)
        page.screenshot(path=str(OUT_DIR / "simple-02-primary-hierarchy.png"))

        # Simple Figure 3 - Primary confidence and comment after selection.
        select_primary(page, "Contingency recognition")
        scroll_to_text(page, "Selected Primary", exact=False, top_offset_px=170)
        page.get_by_placeholder("Optional note about this marking").first.wait_for(
            state="visible", timeout=10000
        )
        page.screenshot(path=str(OUT_DIR / "simple-03-primary-selected-confidence-comment.png"))

        # Simple Figure 4 - all component choices are visible with confidence/comment.
        scroll_to_text(page, "Context (A time", exact=False, top_offset_px=230)
        assert_visible(page, "Answer Marking", exact=False)
        assert_visible(page, "Behavior (An action described in the Answer", exact=False)
        page.screenshot(path=str(OUT_DIR / "simple-04-components-confidence-comments.png"))

        # Simple Figure 5 - rule taxonomy choices after Primary 3 or Rule.
        select_primary(page, "Emerging self-rule")
        scroll_to_text(page, "Rule Taxonomy", exact=False, top_offset_px=150)
        assert_visible(page, "Rule Source", exact=False)
        page.screenshot(path=str(OUT_DIR / "simple-05-rule-taxonomy.png"))

        # Simple Figure 6 - evidence, review flags, notes, and save area.
        scroll_to_text(page, "Answer Evidence and Notes", exact=False, top_offset_px=180)
        assert_visible(page, "Answer Evidence Span / Meaning Unit", exact=False)
        page.screenshot(path=str(OUT_DIR / "simple-06-evidence-flags-notes-save.png"))

        # Simple Figure 7 - User Manual with screenshot tabs.
        page.get_by_text("User Manual", exact=True).first.click()
        page.get_by_text("As the annotator, code the Answer response first", exact=False).first.wait_for(
            state="visible", timeout=30000
        )
        page.screenshot(path=str(OUT_DIR / "simple-07-user-manual-tabs.png"))

        browser.close()

    hashes = {}
    for png in sorted(OUT_DIR.glob("*.png")):
        data = png.read_bytes()
        h = hash(data)
        hashes.setdefault(h, []).append(png.name)
    dupes = [names for names in hashes.values() if len(names) > 1]
    if dupes:
        print("WARNING: duplicate screenshots detected:", dupes)
        sys.exit(1)
    print(f"Saved {len(hashes)} unique screenshots to {OUT_DIR}")


if __name__ == "__main__":
    main()
