# CLAUDE.md — cif-portal

Conventions for Claude Code working in this repo.

## Repo purpose
Signed-in customer portal that surfaces Vergent loan data to the borrower.
Deployed to AWS (us-east-1, account `730667140069`) via SAM + S3 +
CloudFront + Cognito + API Gateway HttpApi.

## Layout
See top-level `README.md`. The stack name is **`cif-portal-dev`**. Round
19B's additive template is `infra/template.yaml` — it expects to be merged
with (or deployed alongside) the base stack that owns the HttpApi +
Cognito pool.

## Secrets — never commit these
- Vergent API key / user password — AWS Secrets Manager
  `cif-portal/vergent/credentials`. Rotate via the Vergent admin UI; update
  the secret after rotation.
- AWS access keys — use the IAM user `claude-portal-deploy`. Do not paste
  keys into commits, issues, or PR descriptions.

## Theme lock
The dashboard must match cashinflash.com. Single source of truth:
`cashinflash/Cif-website` repo → `css/style.css` (Poppins font, green
`#0E8741`, navy `#1a1a2e`, 50 px button radius, 12 px card radius, organic
blobs).

## Coding conventions
- Python 3.12, arm64 Lambdas, no extra pip deps unless essential (stdlib
  `urllib` over `requests`, boto3 is pre-installed).
- JS: no bundler, no framework. Plain DOM. `sessionStorage` for the ID
  token, never `localStorage`.
- CSS: keep `dashboard.css` self-sufficient; portal.css may drift.
- No PII / card numbers / full SSNs / full API keys in logs. Mask before
  logging.

## Tests / validation before commit
- Lint: `python3 -m py_compile backend/handlers/loans.py`
- Visual: `python3 -m http.server -d frontend 8000` — open
  `localhost:8000/dashboard.html`, set a fake token in sessionStorage:
  `sessionStorage.cif_id_token = '<paste ID token from prod sign-in>'`.

## Git
- Develop on `claude/continue-previous-session-<suffix>`. Push to
  `origin`. PRs only on explicit user request.
