"""Quick smoke checks for onboarding copy, key UI strings, and fragile HTML patterns."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
src = APP.read_text(encoding="utf-8")
ast.parse(src)

plain = src.split("PLAIN_OVERVIEW_MD =")[1].split("PLAIN_GLOSSARY_MD =")[0]
training_fn = src.split("def page_simple_labeling_training")[1].split("def page_my_stats")[0]
score_ruler_fn = src.split("def render_training_score_ruler")[1].split("def render_training_field_references")[0]
header_stats_fn = src.split("def render_header_stats")[1].split("\ndef ")[0]
qa_workspace_fn = src.split("def _render_qa_labeling_workspace")[1].split("def split_into_sentences")[0]

# Streamlit treats indented HTML lines as code blocks — never indent `<div` inside markdown HTML.
indented_html_in_score_ruler = bool(
    re.search(r'"""\s*\n\s+<div', score_ruler_fn)
    or re.search(r"f\"\"\"\s*\n\s+<div", score_ruler_fn)
)

checks = {
    "syntax OK": True,
    "4 preliminary score examples": "render_preliminary_examples" in src and "Nothing connects" in (
        ROOT / "docs" / "manual_images" / "preliminary-examples-scores.svg"
    ).read_text(encoding="utf-8"),
    "scores 0 through 3": all(
        x in (ROOT / "docs" / "manual_images" / "preliminary-examples-scores.svg").read_text(encoding="utf-8")
        for x in ("Nothing connects", "Glucose change only", "Cause and effect", "Starting to change")
    ),
    "Initial Training label": "Initial Training" in src,
    "training practice lede": "TRAINING_PAGE_LEDE" in src and "render_training_golden_rules" in src,
    "training no preliminary dup": "render_preliminary_examples()" not in training_fn,
    "training uses subheaders": 'st.subheader("Three rules")' in training_fn
    and 'st.subheader("Primary score at a glance")' in training_fn,
    "score ruler css classes": "score-ruler-row" in src and "score-ruler-title" in src,
    "score ruler no inline flex": "display:flex" not in score_ruler_fn,
    "score ruler no indented html": not indented_html_in_score_ruler,
    "score ruler safe html": "render_html_markdown" in score_ruler_fn,
    "training refs use level-card": 'class="level-card"' in src.split("def render_training_field_references")[1].split("def page_simple_labeling_training")[0],
    "no pick lower in plain overview": "pick the **lower**" not in plain,
    "golden rule no imagination": "no room for imagination" in src,
    "Step 1 default nav": 'else "Step 1' in src or "else 'Step 1" in src,
    "admin-only step 6": "user_is_admin(user)" in src and "Step 6" in src,
    "click evidence picker": "evidence_pick_" in src,
    "3 samples per score level": plain.count('"It was fine."') >= 1 and plain.count("Walking after meals") >= 1,
    "Behavior Form diet/exercise": "diet or exercise change" in plain,
    "G2 study timeline diagram": (ROOT / "docs" / "manual_images" / "g2-study-timeline.svg").exists(),
    "render_g2_study_timeline": "def render_g2_study_timeline" in src,
    "contingency chain mini diagram": (ROOT / "docs" / "manual_images" / "contingency-chain-mini.svg").exists(),
    "memory hook in step 1": "Memory hook" in src,
    "render_svg_embed": "def render_svg_embed" in src,
    "manual pdf export": (ROOT / "manual_pdf.py").exists(),
    "auth remember me": "Keep me signed in on this device" in src,
    "read_auth_token": "def read_auth_token" in src,
    "scoring workflow diagram": (ROOT / "docs" / "manual_images" / "scoring-workflow-simple.svg").exists(),
    "render_html_markdown helper": "def render_html_markdown" in src,
    "header stats safe html": "render_html_markdown" in header_stats_fn,
    "header stats no team_pill hack": "{team_pill}" not in src,
    "step4 qa panel safe html": "render_html_markdown" in qa_workspace_fn
    and 'f"""\n        <div class="sticky-qa-panel"' not in qa_workspace_fn,
    "sign out clears cookie restore": "def sign_out_user" in src and "_signed_out" in src,
    "persist user session helper": "def persist_user_session" in src,
    "restore does not clear on missing user": "users.json may be mid-write" in src,
    "test drive answer key": "def render_test_drive_item_feedback" in src,
    "test drive inline feedback": "test_drive_show_feedback" in src,
    "test drive explanation steps": '"explanation_steps"' in src and "Why Primary 2?" in src,
    "test drive includes primary 3": '"emerging_self_rule"' in src.split("SIMPLE_TEST_DRIVE_ITEM_IDS")[1].split("def simple_test_drive_items")[0],
}

failed = [k for k, v in checks.items() if not v]
print("Checks:")
for k, v in checks.items():
    print(f"  {'PASS' if v else 'FAIL'}: {k}")

if failed:
    raise SystemExit(1)
print("All checks passed.")
