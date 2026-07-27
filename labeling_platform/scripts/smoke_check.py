"""Smoke-test synthetic demo assets against app data contracts."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bcrypt
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "labeling_assets"
GLUCOSE = ROOT / "glucose_data"
PLAT = ROOT / "labeling_platform"


def fail(msg: str) -> None:
    print("FAIL:", msg)
    sys.exit(1)


def build_qa_items(items: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for item in items:
        grouped.setdefault(item["subject_id"], []).append(item)
    qa_items: list[dict] = []
    for subject_id in sorted(grouped.keys()):
        rows = sorted(grouped[subject_id], key=lambda x: int(x["line_no"]))
        i = 0
        while i < len(rows) - 1:
            q = rows[i]
            a = rows[i + 1]
            if q.get("speaker_role") == "interviewer" and a.get("speaker_role") == "subject":
                qa_items.append(
                    {
                        "qa_id": f"{subject_id}_Q{int(q['line_no']):03d}_A{int(a['line_no']):03d}",
                        "subject_id": subject_id,
                        "question_en": q.get("text_en", ""),
                        "answer_en": a.get("text_en", ""),
                    }
                )
                i += 2
            else:
                i += 1
    return qa_items


def main() -> None:
    required = [
        ASSETS / "bilingual_line_items.jsonl",
        ASSETS / "codebook_codes_flat_oneline.csv",
        ASSETS / "codebook_tree.json",
        ASSETS / "simple_check_samples.csv",
        ASSETS / "annotations_qa.csv",
        ASSETS / "users.json",
        GLUCOSE / "G2_demographics.csv",
        GLUCOSE / "G2_computed_cgm.csv",
        GLUCOSE / "G2_Raw_cgm.csv",
        PLAT / "app.py",
        PLAT / "requirements.txt",
        PLAT / "USER_MANUAL.md",
    ]
    for path in required:
        if not path.exists():
            fail(f"missing {path.relative_to(ROOT)}")

    items = []
    with (ASSETS / "bilingual_line_items.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            obj = json.loads(line)
            for key in ("item_id", "subject_id", "line_no", "speaker_role", "text_en", "text_es"):
                if key not in obj:
                    fail(f"line item missing {key}")
            if obj["subject_id"].startswith("G2"):
                fail(f"real subject id leaked: {obj['subject_id']}")
            items.append(obj)

    qa = build_qa_items(items)
    if len(qa) < 6:
        fail(f"too few QA pairs: {len(qa)}")

    checks = pd.read_csv(ASSETS / "simple_check_samples.csv", dtype=str)
    qa_ids = {q["qa_id"] for q in qa}
    missing = [x for x in checks["qa_id"] if x not in qa_ids]
    if missing:
        fail(f"check samples not in QA set: {missing}")

    codes = pd.read_csv(ASSETS / "codebook_codes_flat_oneline.csv")
    if codes.empty:
        fail("empty codebook")

    users = json.loads((ASSETS / "users.json").read_text(encoding="utf-8"))
    for name, password in (("demo", "demo1234"), ("admin", "admin1234")):
        if name not in users:
            fail(f"missing user {name}")
        ok = bcrypt.checkpw(password.encode(), users[name]["password_hash"].encode())
        if not ok:
            fail(f"password hash mismatch for {name}")

    demo = pd.read_csv(GLUCOSE / "G2_demographics.csv")
    if set(demo["subject_id"]) != {"DEMO01", "DEMO02", "DEMO03"}:
        fail(f"unexpected demographics subjects: {sorted(demo['subject_id'])}")

    # no real G2 IDs in text assets
    for path in ASSETS.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(f"G2{i:03d}" in text for i in range(1, 200)):
            # allow none
            import re

            found = sorted(set(re.findall(r"G2\d{3}", text)))
            if found:
                fail(f"real G2 IDs in {path.name}: {found}")

    print("OK smoke checks passed")
    print(f"  subjects=3  line_items={len(items)}  qa_pairs={len(qa)}  checks={len(checks)}  codes={len(codes)}")


if __name__ == "__main__":
    main()
