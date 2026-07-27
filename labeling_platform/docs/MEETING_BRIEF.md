# Labeling Platform — Meeting Brief

**Date:** June 1, 2026
**Prepared for:** PI / faculty and coding team review
**Topic:** Annotator training, the "Test Drive" gate, and Prolific-style attention checks

---

## 1. Purpose of this meeting

1. Confirm the recent usability and training updates to the labeling interface.
2. Review how we verify that annotators are reading carefully (attention / quality checks),
   in line with Prolific's recommendation to embed clear, simple check items.
3. Decide on any remaining policy questions (thresholds, enforcement, item selection).

---

## 2. Platform overview (one paragraph)

The platform is an internal Streamlit app where annotators label each interview **Answer** on a
**Primary Hierarchy** scale (0–4, language maturity / contingency), mark optional **Components**
(Context, Behavior, Consequence, Rule), and, when a rule is present, record **Rule Source** and
**Behavior Form**. Annotators must complete **Labeling Training** before the **Annotate** page unlocks.
Inter-rater agreement and gold accuracy are tracked on an **Agreement Dashboard**.

---

## 3. Recent updates (from review feedback)

| # | Feedback | What we changed |
|---|----------|-----------------|
| a | Quick-reference titles turned dark/unreadable once expanded | Expander headers now have explicit, readable styling in both light and dark themes (title stays legible when expanded or hovered). |
| b | We had quick references for *Primary Hierarchy* and *Components*, but not for *Rule Source* | Added a **Rule Source quick reference** (N/A · Self-generated · Borrowed · Mixed/Unclear) and, for consistency, a **Behavior Form quick reference** on the training page. |
| c | "Calibration" forced matching of full prior answers; this is too strong for subjective items | Renamed to **Test Drive**. It no longer grades Components / Rule Source / Behavior Form against a "correct" key. It only checks **Primary Hierarchy** on **3 unambiguous items** to confirm basic readiness, with language that explicitly acknowledges that real data is often subjective. |

---

## 4. How we verify annotator effort (two distinct mechanisms)

A common point of confusion: the 6 training items are **not** our attention checks. There are two
separate systems.

### 4.1 Labeling Training / Test Drive — onboarding (shown openly)
- 6 worked examples that teach the scale, shown with answers and rationale.
- The **Test Drive** gate checks **Primary Hierarchy only**, on **3 clear items** (Primary 0, 2, and 4).
- Goal: a shared starting interpretation — **not** a pass/fail effort test.

### 4.2 Hidden Check Samples — Prolific-style quality control (hidden)
- **58 gold-labeled items** embedded in the real labeling set across **29 subjects** (~2 per subject).
- Annotators do **not** know which items are checks.
- The platform automatically compares saved labels to the expected (gold) labels and reports
  gold accuracy for Primary, Components, Rule Source, and Behavior Form.

### 4.3 Attention checks (new) — the "is the annotator paying attention?" subset
- **11 of the 58** hidden items are now formally tagged as **attention checks**.
- These are the **unambiguous Primary 0 (no-contingency) answers** — the answer is obvious, so a
  careless annotator is expected to get them wrong.
- **Flag rule:** a coder is flagged for review when they have reached **≥ 3** attention checks and
  their Primary accuracy on them is **below 70%**. (Both numbers are configurable.)
- **Where it shows:**
  - **Annotator:** a prominent red banner at the top of the Annotate page asking them to slow down,
    plus a pass count in **My Stats**.
  - **Admin:** a flagged-coders warning and added columns (Attention Checks Reached / Accuracy / Flag)
    on the **Agreement Dashboard**.
- **Important:** flagging is currently **advisory** — it warns and surfaces for review; it does **not**
  auto-reject or lock the account.

---

## 5. The 6 training items (shown to annotators)

| # | Primary | Question → Answer (abbreviated) | Test Drive |
|---|---------|----------------------------------|:---------:|
| 1 | 0 | Anything you did not like about the videos? → "No. Everything was good." | ✓ |
| 2 | 1 | How would you interpret what you saw? → "My glucose went up after lunch, but I don't know what caused it." | |
| 3 | 2 | What caused the high glucose alert? → "When I ate rice at dinner, my glucose went up." | ✓ |
| 4 | 3 | Any changes to eating habits? → "Soda makes my glucose spike, so I'm trying to drink water instead." | |
| 5 | 4 | Could you create a general rule? → "Tortillas at night spike me, so now I avoid tortillas at dinner." | ✓ |
| 6 | 3 | Any changes to eating habits? → "My doctor told me sugary drinks raise glucose, so I plan to stop buying soda." (Borrowed rule) | |

---

## 6. The 11 attention-check items (hidden; Primary 0)

All are clear "no contingency" answers (e.g., the device did not interfere, no change in habits, or a
general comment with no behavior–outcome link).

| Subject | Item ID | Expected Primary |
|---------|---------|:----------------:|
| DEMO## | DEMO##_Q011_A012 | 0 |
| DEMO## | DEMO##_Q027_A028 | 0 |
| DEMO## | DEMO##_Q031_A032 | 0 |
| DEMO## | DEMO##_Q047_A048 | 0 |
| DEMO## | DEMO##_Q029_A030 | 0 |
| DEMO## | DEMO##_Q029_A030 | 0 |
| DEMO## | DEMO##_Q039_A040 | 0 |
| DEMO## | DEMO##_Q009_A010 | 0 |
| DEMO## | DEMO##_Q029_A030 | 0 |
| DEMO## | DEMO##_Q043_A044 | 0 |
| DEMO## | DEMO##_Q033_A034 | 0 |

---

## 7. Open questions for discussion

1. **Threshold:** Is **< 70%** attention-check accuracy (after **≥ 3** items) the right flag point,
   or should it be stricter (e.g., any clear item missed)?
2. **Enforcement:** Keep flagging advisory, or add a hard stop (pause an annotator after repeated
   failures) and/or a Prolific completion/rejection-code integration?
3. **Item count and balance:** Are 11 attention checks across 29 subjects enough, and should we add a
   few more "very obvious" items?
4. **Coverage:** Should we guarantee each annotator encounters a minimum number of attention checks
   early in their work?
5. **Subjectivity:** Confirm we are comfortable treating only Primary 0 items as pass/fail, and the
   subjective Primary 3/4 items as quality/agreement metrics rather than effort tests.

---

## 8. Companion materials

- An editable item table is available as a canvas (`canvases/training-items.canvas.tsx`) for live
  edits during the meeting.
- Full interface documentation is in `USER_MANUAL.md`.
