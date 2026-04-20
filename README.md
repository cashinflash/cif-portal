# cif-portal

Customer-facing portal for Cash in Flash — sign-in, dashboard, payments,
documents. Deploys to `d1zucrj1ouu3c.cloudfront.net` (future:
`portal.cashinflash.com`).

## Layout

```
frontend/              static site deployed to S3 + CloudFront
  css/dashboard.css      dashboard-specific styles (blobs, cards, skeleton)
  js/dashboard.js        dashboard controller (auth, fetch, DOM)
  dashboard.html         the signed-in landing page
  images/                logo + favicon (copied from cif-website)
  fonts/                 self-hosted Poppins

backend/handlers/
  loans.py               Round 19B — active loan + recent activity
                         (calls Vergent CustomerPortal API)

infra/
  template.yaml          SAM template for the Round 19B additive Lambda
  samconfig.toml         `sam deploy` defaults

docs/
  VERGENT_INTEGRATION.md reference: endpoints, auth, response shapes
```

## Deploy (next session)

Prereqs: AWS CLI + SAM CLI, credentials for IAM user
`claude-portal-deploy` in account `730667140069`.

```bash
# 1. Frontend
aws s3 sync frontend/ s3://cif-portal-frontend-dev-730667140069 --delete \
  --exclude ".DS_Store" --exclude "*.map"
aws cloudfront create-invalidation \
  --distribution-id <DIST_ID> --paths '/*'

# 2. Backend (loans Lambda)
cd infra
sam build --use-container
sam deploy \
  --parameter-overrides \
    HttpApiId=<from base stack> \
    JwtAuthorizerId=<from base stack> \
    VergentSecretArn=arn:aws:secretsmanager:us-east-1:730667140069:secret:cif-portal/vergent/credentials-XXXXXX
```

## Branch policy

Development happens on
`claude/continue-previous-session-<suffix>`; open a PR to `main` for
release.

## Round history

- 15 — portal scaffold (Cognito + HttpApi + CloudFront)
- 16 — CLAUDE.md files (incomplete, tracked in parent docs repo)
- 17 — Vergent V2 pivot
- 18 — portal UX (phone optional, SSN mask, header polish)
- 19A — signup uniqueness (PreSignUp trigger writes `custom:vergentCustomerId`)
- **19B** — customer dashboard (this repo, first commit)
