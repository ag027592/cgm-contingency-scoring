# Security notes

## Demo credentials

This repository includes **synthetic** demo accounts (`demo` / `admin`) so
reviewers can run the Streamlit app immediately. Those passwords are public by
design.

If you deploy this software beyond a local demo:

1. Replace `labeling_assets/users.json` with private accounts.
2. Delete or rotate the demo users.
3. Keep `labeling_assets/.session_secret` out of version control (already gitignored).
4. Never commit real study transcripts, CGM exports, videos, or screenshots.

## Reporting issues

Open a GitHub issue for software defects. Do **not** attach participant data
or PHI when filing bugs.
