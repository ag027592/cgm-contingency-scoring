# CGM Contingency Speech Scoring Platform

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/UI-Streamlit-FF4B4B.svg)](https://streamlit.io/)

Open-source **human annotation platform** for scoring how people talk about
learning from continuous glucose monitoring (CGM) feedback — specifically the
*contingency* structure of post-visit interview answers (context → behavior →
consequence → rule).

This public repository ships **software + synthetic demo data only**.
It does **not** contain real study transcripts, CGM sensor streams, videos, or
annotator accounts from the G1/G2 studies.

## What it does

Coders open a Streamlit app, complete a short **Test Drive** training gate, then
label each interview Q/A item on a **Primary Hierarchy** (0–4) with optional
**Components** (Context / Behavior / Consequence / Rule) and rule taxonomy.
Hidden **attention checks** and an **Agreement Dashboard** support quality
control for multi-coder deployments.

| Feature | Description |
|---|---|
| Bilingual Q/A cards | English / Spanish line items with keyword highlighting |
| Primary Hierarchy 0–4 | From no-contingency answers to self-generated future rules |
| Components + rule taxonomy | Context, behavior, consequence, rule source, behavior form |
| Test Drive gate | Onboarding check before Annotate unlocks |
| Attention checks | Hidden unambiguous items to flag careless coding |
| CGM context panel | Optional demographics / phase metrics beside the language task |
| Agreement dashboard | Pairwise agreement and gold accuracy for admins |

## Quick start

```bash
cd labeling_platform
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix:    source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

**Demo login** (synthetic accounts only):

| Username | Password | Role |
|---|---|---|
| `demo` | `demo1234` | coder |
| `admin` | `admin1234` | admin |

Change these immediately if you deploy beyond a local demo.

## Repository layout

```
cgm-contingency-scoring/
├── labeling_platform/     # Streamlit app, docs, helper scripts
├── labeling_assets/       # codebook + synthetic demo Q/A + empty annotations
├── glucose_data/          # synthetic DEMO demographics / CGM stubs
├── README.md
├── CITATION.cff
└── LICENSE
```

Expected runtime layout matches the app's `BASE_DIR` resolution
(`labeling_platform/` sits next to `labeling_assets/` and `glucose_data/`).

## Privacy and IRB

**Do not commit real participant data into this repository.**

Excluded from this release on purpose:

- G1/G2 post-visit transcripts (English / Spanish)
- Raw and computed CGM files from the study
- Interview videos / audio
- Real annotator `users.json` password hashes and names
- Session secrets
- Live-session PNG screenshots that may display participant text

To run on your own IRB-approved data, replace the synthetic files under
`labeling_assets/` and `glucose_data/` with de-identified exports that match the
same schemas, and keep those files **outside** public git history.

## Related study materials (not in this repo)

Internal GCM project folders also contain LIWC analyses, proposal drafts, and
HITL planning docs. Those remain private until the study team decides what can
be shared under the IRB and data-use agreements.

## Citation

```bibtex
@misc{chou2026cgmscoring,
  title        = {CGM Contingency Speech Scoring Platform},
  author       = {Chou, Huang-Cheng},
  year         = {2026},
  howpublished = {GitHub repository},
  note         = {Open-source annotation software with synthetic demo data},
  url          = {https://github.com/ag027592/cgm-contingency-scoring}
}
```

## License

MIT for the software and documentation in this repository.
Synthetic demo utterances are fictional examples for software demonstration.
