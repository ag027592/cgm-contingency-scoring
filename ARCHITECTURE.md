# Architecture

```
cgm-contingency-scoring/
├── labeling_platform/          # Streamlit UI + docs + scripts
│   ├── app.py                  # single-file application (~7k LOC)
│   ├── USER_MANUAL.md          # coder / PI manual
│   ├── manual_pdf.py           # PDF export helper
│   ├── docs/                   # meeting brief + SVG diagrams
│   └── scripts/                # smoke_check, screenshot helpers
├── labeling_assets/            # runtime data next to the app
│   ├── bilingual_line_items.jsonl
│   ├── codebook_*.csv / .json
│   ├── simple_check_samples.csv
│   ├── annotations_qa.csv
│   └── users.json
└── glucose_data/               # optional CGM context panel inputs
    ├── G2_demographics.csv
    ├── G2_computed_cgm.csv
    └── G2_Raw_cgm.csv
```

`app.py` resolves `BASE_DIR` as the parent of `labeling_platform/`, so
`labeling_assets/` and `glucose_data/` must sit beside it.

## Scoring model (what coders label)

Each interview **Answer** is scored for *contingency-sensitive verbal behavior*
under CGM feedback:

| Primary | Meaning (short) |
|---|---|
| 0 | No contingency (evaluation / non-answer) |
| 1 | Outcome without a clear cause |
| 2 | Behavior/context linked to glucose outcome |
| 3 | Enacted or intended behavior change |
| 4 | Explicit self-generated future rule |

Optional **Components**: Context, Behavior, Consequence, Rule.  
When a rule is present: **Rule Source** and **Behavior Form**.

## Quality-control stack

1. **Test Drive** — onboarding gate on unambiguous Primary examples  
2. **Hidden gold / attention checks** — embedded items; low attention accuracy flags a coder  
3. **Agreement Dashboard** — pairwise agreement + gold accuracy for admins  

## Design constraints that matter for hiring managers

- Built for **multi-rater** clinical coding, not single-pass crowdsourcing alone  
- Separates **language coding** from CGM numbers (CGM is supporting evidence)  
- Bilingual EN/ES presentation with keyword highlighting  
- Local auth (bcrypt + signed cookie) suitable for lab deployment without a cloud IdP  
- Data files are swappable: public repo ships synthetic demos; IRB data stays private  
