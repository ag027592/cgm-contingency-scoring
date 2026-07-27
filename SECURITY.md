# Security notes

## Demo credentials

This repository includes **synthetic** demo accounts (`demo` / `admin`) so
reviewers can run the Streamlit app immediately. Those passwords are public by
design.

When the bundled Q/A data contains only `DEMO*` subject IDs, the app
automatically enters **public demo mode**:

- registration is disabled;
- annotations are stored only in the visitor's Streamlit session;
- `users.json`, `annotations_qa.csv`, and `.session_secret` are not modified;
- the UI displays a persistent synthetic-data / session-only notice.

Set `CGM_PUBLIC_DEMO=0` only for a controlled private deployment. Set
`CGM_SESSION_SECRET` in the deployment environment if login cookies must
survive process restarts.

If you deploy this software beyond a local demo:

1. Replace `labeling_assets/users.json` with private accounts.
2. Delete or rotate the demo users.
3. Keep `labeling_assets/.session_secret` out of version control (already gitignored).
4. Never commit real study transcripts, CGM exports, videos, or screenshots.

## Reporting issues

Open a GitHub issue for software defects. Do **not** attach participant data
or PHI when filing bugs.
