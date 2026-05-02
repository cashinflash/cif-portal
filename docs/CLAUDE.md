# CLAUDE.md — cif-portal

**Purpose of this file:** the context a fresh Claude session needs to
pick up work on this repo without backtracking. Keep it accurate —
update it every time we change an infrastructure ID, add a deploy
step, learn a gotcha, or finish a feature.

Last updated: 2026-04-21 (session_019VAj8MjuyDmPbJzHGUDxTA).

---

## Repo purpose

Signed-in customer portal for Cash in Flash (Dhan Corporation,
California DFPI License #214840). Lets existing Vergent LMS customers:

- Sign up with an email locked to what Vergent has on file
- Log in with Cognito + MFA (email OR SMS, customer's choice)
- View active loan balance, APR, autopay flag, payment progress, and
  transaction history on a branded dashboard
- Hand off into Vergent's apply UI for a new-loan request

Not in scope: marketing site (lives at `cashinflash/Cif-website`),
Vergent-side staff tools, loan origination UI (lives at
`cashinflash/cif-apply`).

---

## Session-handoff checklist (read first)

If you're a new Claude session picking this up, read these **in order**
before making any changes:

1. This file (CLAUDE.md).
2. `docs/VERGENT_INTEGRATION.md` — v1 vs v2 APIs, shapes, failure modes.
3. `docs/2FA_SETUP.md` — MFA flow details.
4. The current branch: `git branch --show-current` should print
   `claude/continue-previous-session-<suffix>`. If not, the new
   session's prompt will tell you which branch to develop on.
5. Recent commits: `git log --oneline -10` tells you what the previous
   session actually shipped.

---

## Layout

```
backend/
  handlers/            # One Lambda per .py file (plus a couple of
                       # helpers that get bundled as a single zip).
    loans.py           # GET  /api/my-profile (now also returns
                       #        addresses + phones for editing),
                       #      /api/my-loans/active,
                       #      /api/my-loans/activity (?loanId=N),
                       #      /api/my-loans/documents (?loanId=N),
                       #      /api/my-loans/documents/{docId}/download
                       #        (?format=pdf invokes the doc-pdf Lambda)
                       # PUT  /api/my-profile/email (queues a change
                       #        request for admin review; does NOT
                       #        write to Vergent directly)
                       # PUT  /api/my-profile/address (queues a change
                       #        request for admin review)
                       # POST /api/my-profile/phone/start-verify
                       #        (Vergent SMS PIN to new number)
                       # POST /api/my-profile/phone/confirm
                       #        (verify PIN + queue change request for
                       #        admin review)
                       # POST /api/my-loan/new (handoff to Vergent)
  doc_pdf/             # Node.js 20 Lambda — HTML → PDF conversion via
                       #   puppeteer-core + @sparticuz/chromium.
                       #   Driven from loans.py via boto3 lambda.invoke
                       #   when a customer hits ?format=pdf on the doc
                       #   download endpoint. x86_64 / 1024 MB / 30 s.
                       #   ~50 MB zip with chromium binary; deployed
                       #   via .github/workflows/deploy-doc-pdf.yml
                       #   (zip → S3 → update-function-code).
    payments.py        # GET /api/my-cards, /api/my-payment/loan-summary
                       # POST /api/my-cards (add new card — forwards
                       #   full PAN over HTTPS to Vergent's
                       #   CustomerPortal/Customer/Cards; Vergent
                       #   tokenizes via Repay server-side)
                       # POST /api/my-payment (charges saved card via
                       #   Vergent → Repay; posts to loan atomically)
    auth_mfa.py        # POST /api/login, /send-code, /verify-code
    twilio_verify.py   # Twilio Verify client (imported by auth_mfa)
    twilio_sms.py      # Legacy Messages client (kept, not used)
    search.py          # POST /api/search (pre-login customer lookup)
    pre_signup.py      # Cognito PreSignUp trigger
    me.py, health.py, probe.py, loans_v1.py  # Support / deprecated
  layer/python/        # Shared code attached as Lambda layer
    aws_secrets.py, responses.py, twilio_sms.py, vergent.py

frontend/              # Static SPA — plain HTML/CSS/JS, no bundler.
  *.html               # dashboard, start, login, signup, search,
                       #   forgot, payments, loans, documents,
                       #   request-loan
  css/dashboard.css    # Dashboard-only styles (tracked in git)
  js/dashboard.js      # Dashboard controller (tracked in git)

infra/
  template.yaml        # SAM additive template (Round 19B — loans Lambda).
  samconfig.toml

docs/                  # Reference material. See VERGENT_INTEGRATION.md,
                       #   2FA_SETUP.md, vergent-swagger.json,
                       #   vergent-v1/v1.pdf (424p reference).

.github/workflows/
  deploy.yml           # Auto-deploy on push to main or claude/** branches.
```

---

## Running infrastructure (us-east-1, account 730667140069)

| Thing | ID / Name |
|---|---|
| Cognito User Pool | `us-east-1_U508xOs95` |
| Cognito App Client | `1mddi61n19hftaldt9t3r622b` |
| API Gateway HTTP API | `anh066l1wf` |
| JWT Authorizer | `ppc9vg` |
| S3 frontend bucket | `cif-portal-frontend-dev-730667140069` |
| CloudFront distribution | `EOV9K12LFKK8T` (→ `d1zucrj1ouu3c.cloudfront.net`) |
| DynamoDB MFA sessions | `cif-portal-mfa-sessions-dev` |
| SES verified domain | `cashinflash.com` (DKIM on) |
| Lambdas (dev) | `cif-portal-loans-dev`, `cif-portal-auth-mfa-dev`, `cif-portal-search-dev`, `cif-portal-pre-signup-dev`, `cif-portal-payments-dev` |

**SES status:** in sandbox as of 2026-04-20; production-access ticket
submitted 4/20, follow-up reply sent 4/20, awaiting AWS response.
Until production is granted, outbound email works only to verified
recipients.

**Twilio:** Verify service SID `VA85600da2af290bef1dfb336014af8f61`,
toll-free number `+18555962274` (carrier verification submitted, 3–5
day turnaround). Branch-new account upgraded off trial 4/20.

---

## Deploy pipeline — GitHub Actions

**Every push to `main` or a `claude/**` branch auto-deploys.** The
workflow lives at `.github/workflows/deploy.yml` and:

1. Checks out the repo with `fetch-depth: 2` so it can diff
   `HEAD^..HEAD`.
2. On `workflow_dispatch` (manual run) sets every output flag to true.
3. On push, greps the diff for known paths to decide which Lambda(s)
   to update and whether to sync the frontend.
4. Zips `backend/handlers/` once and calls
   `aws lambda update-function-code` per changed Lambda.
5. Runs `aws s3 sync frontend s3://…` **without `--delete`** (see
   warning below) and invalidates CloudFront `"/*"`.

**Required GitHub repo secrets** (set under Settings → Secrets and
variables → Actions):

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

Both belong to the `claude-portal-deploy` IAM user. AWS enforces a
max of 2 keys per user — rotate by creating a new key, updating the
secrets, confirming a deploy works, then deleting the old key.

**Manual full re-deploy:** Actions tab → "Deploy cif-portal" → Run
workflow → pick a branch.

---

## ⚠️ Frontend gotcha — files that live only in S3

The repo tracks **`dashboard.html` + `dashboard.css` + `dashboard.js`**
and the page files used by the main flows. It does **not** track:

- `css/portal.css`   (styles for start/login/signup/search/forgot)
- `css/cif-brand.css` (brand variables)
- `js/portal.js`      (shared auth JS)
- `js/portal-page.js` (page-level init)
- `images/favicon.png`, `images/logo.png`

These files live only in the S3 bucket. The deploy workflow used to
use `aws s3 sync --delete`, which deleted them on the first run
(2026-04-21, breaking start/login/signup). The `--delete` flag has
since been removed from `deploy.yml` — don't put it back. If you need
to remove a file from S3, do it manually.

**If these files get nuked again**, restore from S3 versioning in the
console: open the bucket, toggle "Show versions", filter by the file
name, delete the "Delete marker" row — the prior version becomes
current again.

**TODO (future):** commit these files to the repo so git is the source
of truth. Until that's done, treat S3 as canonical for the above
paths.

---

## Vergent integration (1-paragraph version)

Two surfaces — v2 (`prod.apim.vergentlms.com/external/shared`,
`x-api-key` + JWT) and v1 (`shared.vergentlms.com/api/api`, service
`Token` header). **We use v1 for everything that actually matters**
(loans, profile, email lookup, history) because v2's
`AuthenticateCognito` is broken for our tenant. v2 is still used for
the `/api/authenticate/handoff/create` endpoint (new-loan redirect).
Full details in `docs/VERGENT_INTEGRATION.md`.

Service token is cached per warm Lambda container for 1 h (see
`loans.py::_get_v1_token`). User id from the auth response is also
cached — needed for `GetCustomerLoanHistory`.

---

## MFA flow (1-paragraph version)

`auth_mfa.py` runs the whole dance server-side:

1. `/login` — `ADMIN_USER_PASSWORD_AUTH` to Cognito. If it returns tokens
   directly, we **hold them in DDB** keyed by a session id and return
   only the session id + masked email/phone to the SPA.
2. `/send-code` — SPA tells us which channel (email or SMS). Email uses
   SES + our branded template. SMS uses Twilio Verify (Twilio stores
   the code, not us).
3. `/verify-code` — Email branch hashes + compares against DDB. SMS
   branch calls Twilio Verify's `VerificationCheck`. On success, we
   return the real Cognito tokens stored from step 1.
4. DDB session TTLs at 10 min. After 3 wrong attempts we delete the
   session.

Full details in `docs/2FA_SETUP.md`.

---

## Secrets — never commit these

All stored in AWS Secrets Manager, `us-east-1`:

| Name | Shape |
|---|---|
| `cif-portal/vergent/credentials` | `{logonName, password, xApiKey}` |
| `cif-portal/twilio/credentials` | `{accountSid, authToken, verifyServiceSid, fromNumber}` |

Rotate via the vendor UI → update the secret → Lambdas pick up the new
value on the next cold start (module-global cache is per container).

**Never** paste access keys into commits, issues, PR descriptions, or
CloudWatch logs. The `_mask_phone` helper in `loans.py` is the pattern
for logging partial identifiers.

---

## Theme lock

Dashboard must match cashinflash.com. Single source of truth:
`cashinflash/Cif-website` repo → `css/style.css` (Poppins font, green
`#0E8741`, navy `#1a1a2e`, 50 px button radius, 12 px card radius,
organic blobs).

---

## Coding conventions

- **Python 3.12, arm64 Lambdas, stdlib-only** unless absolutely
  necessary (`urllib` over `requests`, `boto3` is pre-installed).
- **JS: no bundler, no framework.** Plain DOM. `sessionStorage` for
  the ID token, never `localStorage`.
- **CSS:** keep `dashboard.css` self-sufficient. `portal.css` may drift
  (and lives only in S3 — see warning above).
- **No PII in logs.** Mask before logging: SSNs, full API keys, card
  numbers, full phone numbers, full emails.
- **Feature flags:** we don't use them — when a feature is ready we
  just ship it.

---

## Tests / validation before commit

- Lint changed Python: `python3 -m py_compile backend/handlers/<file>.py`
- Lint JS: `node --check frontend/js/<file>.js`
- Visual (local): `python3 -m http.server -d frontend 8000` then open
  `http://localhost:8000/dashboard.html` and paste a real ID token into
  `sessionStorage.cif_id_token`.
- For frontend changes — after deploy, hard-refresh (Cmd+Shift+R) and
  check in a **private/incognito window** too so local cache doesn't
  lie to you.

---

## Git

- Develop on `claude/continue-previous-session-<suffix>` (the suffix
  is given in the session prompt).
- Push to `origin`. PRs only on explicit user request.
- The deploy workflow fires on every push to `claude/**` — if you push
  a WIP commit, it WILL deploy. Push only when the commit is ready.
- Never push to `main` without explicit user request.
- Never `--no-verify`, never force-push to main/master.

---

## Recent work log

Update this section at the end of each session. Newest first.

### 2026-05-02 — Phase E: customer confirmations + phone-verify diagnostic
- New `_send_customer_confirmation()` in loans.py fires a banking-
  style "we received your request" SES email to the customer's
  sign-in inbox right after the admin notification, inside
  `_create_change_request()`. All three flows (email/address/phone)
  get acknowledged automatically. Best-effort — failures log but
  don't propagate; queue is still source of truth.
- `start_phone_verify` / `confirm_phone_verify` now log the
  upstream status + first 400 chars of the raw response body to
  CloudWatch on every attempt (with last-4-digits of phone for
  PII safety) and surface `upstreamStatus` + `upstreamBody` in
  the 502 JSON response. Added a single retry with uppercase
  `SMS` (the {type} placeholder in the doc) when the lowercase
  `sms` path returns 404. This is the diagnostic surface needed
  to figure out why Vergent's SMS validate endpoint is returning
  non-2xx for our tenant — pivot from there based on what the
  diagnostic shows.
- `_v1_request` extended with optional `return_raw=True` so callers
  that need the raw body for diagnostics can opt in without
  changing the default `(status, parsed)` shape.

### 2026-05-02 — Phase D: profile change-requests via admin-approval queue
- Architecture pivot from the original Phase C plan. Profile edits
  on /profile.html (email / phone / address) no longer write to
  Vergent directly. Customers submit a *change request* that lands
  in a DDB queue and fires an admin-notification email; an admin
  reviews and applies the change in Vergent admin (or, eventually,
  a CIF internal admin portal). Sidesteps the v1 UpdateCustomer*
  body-shape unknowns and matches how traditional banks gate KYC
  field updates.
- New DDB table `cif-portal-profile-change-requests-dev`:
  PK=requestId (S), pay-per-request, TTL on `expiresAt`
  (90-day audit-trail retention). Items carry customerId, field
  ('email'|'phone'|'address'), currentValue, requestedValue,
  status='pending', requestedAt, requestedByEmail, plus optional
  meta (e.g. `phoneVerified=true` once the SMS PIN passes).
- New env vars on the loans Lambda:
    PROFILE_REQUESTS_TABLE   — DDB table name
    ADMIN_NOTIFY_EMAIL       — where SES sends the alert (default
                                 info@cashinflash.com)
    SES_SENDER_EMAIL         — Source on the SES SendEmail call
                                 (default no-reply@cashinflash.com)
- New IAM grants on the loans Lambda execution role (via
  provision-loans.yml inline policy `cif-portal-loans-profile-requests`):
    dynamodb:PutItem|GetItem|UpdateItem|Query on the table
    ses:SendEmail|SendRawEmail (Resource: *)
- Helpers added in loans.py:
    _create_change_request(cid, claims, field, current, requested,
                            extra_meta) — DDB write + email
    _send_admin_notification(...) — SES text+HTML message with
                                     current vs requested + UUID
- Phone change still has the two-step SMS PIN flow (security
  boundary — a stolen session can't queue a fake number for the
  admin to approve later). The PIN start/confirm calls DO go to
  Vergent directly; only the field-mutation step is queued.
- Frontend (profile.js): banners reworded "submitted for review";
  local cache no longer updates the displayed value (waits for
  admin approval).
- "Need to change your name?" footer block removed from
  profile.html (CIF doesn't advertise self-service for that even
  via phone).
- _v1_request() helper still present (used by the SMS PIN flow).
- Out of scope for Phase D: an admin-approval UI; Cognito sign-in
  email/phone sync; a "pending review" badge on /profile.html
  showing the customer's queued requests. All deferrable to Phase E.

### 2026-05-01 — Phase B: idle-based session timeout (online-banking style)
- session.js converted from token-expiry timer to industry-standard
  10-min idle timer + 1-min warning. Activity (click / keydown /
  scroll / mousemove / touchstart) resets the clock. Silent
  background refresh of the Cognito IdToken when it nears expiry
  AND the customer is still active. Activity is ignored while the
  warning modal is showing so a passing mouse-twitch doesn't
  auto-extend.
- Forced logouts redirect to /start.html?reason=session_expired
  (or signed_out) and start.html now surfaces a friendly inline
  banner explaining what happened.

### 2026-05-01 — Phase A: CORS lockdown + security headers + cleanup
- CORS Access-Control-Allow-Origin moved from '*' to env-driven
  PORTAL_ORIGIN (defaults to dev CloudFront). Affects all 5 entry
  points (loans, auth_mfa, if_submit, loans_v1, layer responses).
- Baseline security response headers on every Lambda response:
  Strict-Transport-Security, X-Content-Type-Options, Referrer-
  Policy, Permissions-Policy.
- New set-portal-origin.yml workflow flips the allowed origin
  without code deploys.
- Bug fix: ClientError caught in loans._render_html_to_pdf but
  never imported.
- Cleanup: ?debug=1 mode removed from /api/my-loans/documents,
  _v1_get_binary deleted, ~150 lines of unreachable POST
  /api/my-cards block deleted, three diagnostic probe logs
  removed.
- Trust signal: DFPI license #214840 now in every signed-in
  page footer.
- Infra: deploy-doc-pdf.yml now applies a 30-day S3 lifecycle
  policy on the artifact bucket.

### 2026-05-01 — Server-side PDF for loan documents (doc-pdf Lambda)
- New Node.js 20 Lambda `cif-portal-doc-pdf-dev` converts Vergent's
  HTML signed-document content to real PDFs via headless Chromium
  (`puppeteer-core` + `@sparticuz/chromium`). x86_64 / 1024 MB / 30s.
- Driven from `loans.py` via `boto3.lambda.invoke` when the customer
  hits `/api/my-loans/documents/{docId}/download?format=pdf`. Without
  that param, the original HTML is served (used by the in-page modal
  viewer for fast inline rendering).
- Two new workflows:
    - `provision-doc-pdf.yml`: creates the Lambda, grants the loans
      Lambda's IAM role `lambda:InvokeFunction` permission on it,
      sets `DOC_PDF_FN_NAME` env var on the loans Lambda. Idempotent.
    - `deploy-doc-pdf.yml`: builds the function zip (npm install +
      zip including chromium binary, ~50 MB), uploads to a private
      S3 bucket `cif-portal-lambda-artifacts-730667140069` (created
      on first run), and runs `lambda update-function-code` against
      the S3 reference. Triggers on push to `backend/doc_pdf/**`.
- Frontend: View button still uses the HTML render (fast modal),
  Download button (and the modal's internal Download) call
  `?format=pdf` to get a real PDF. Filenames swapped from `.html`
  to `.pdf`. Modal-stuck-on-loading bug fixed by overlaying the
  loading panel via CSS instead of toggling `iframe.hidden` (Chrome
  skips the load event for `display:none` iframes).

### 2026-05-01 — My Loans page (Phases 1 + 2)
- **Phase 1 (commit `e561107`)**: replaced `loans.html` stub with real
  list-and-detail page. Lists every loan newest-first; deep-linkable
  detail view at `/loans.html?id=N` shows summary, full details, and
  transaction history. New `frontend/js/loans.js`, CSS additions in
  `dashboard.css`. `get_activity()` extended to accept `?loanId=N`
  with ownership validation. No infra changes — reuses existing
  `/api/my-loans/active` (whose `allLoans` field already had every
  loan) and `/api/my-loans/activity`.
- **Phase 2**: signed loan agreements + disclosures now viewable
  inline. Two new routes on the loans Lambda:
    - `GET /api/my-loans/documents?loanId=N` → list of docs
      (id, fileName, displayName, documentDate, kind, loanId)
    - `GET /api/my-loans/documents/{docId}/download` → binary PDF
      response, base64-encoded, with Content-Type and inline
      Content-Disposition. 6 MB Lambda response cap is fine for
      typical signed agreements.
  Both use the **v1 LMS API** (`/V1/customer/{cid}/docs/loan/{hdr}`,
  `/V1/customer/{cid}/docs/loan/{hdr}/OtherFiles`,
  `/V1/docs/{docId}/download`) with our existing service Token
  header — no new auth flow. Ownership is enforced by walking the
  customer's loans and confirming the requested docId belongs to one
  of them before fetching.
  Frontend: documents card on the loan-detail view fetches the list
  and renders each doc with a "View" button that does a
  `fetch + URL.createObjectURL(blob) + window.open` so the
  Authorization header travels with the request.
  New `provision-loans.yml` workflow registers all loans Lambda
  routes idempotently (run once after merging this commit).
- Updated `VERGENT_INTEGRATION.md` to reflect that v1 LMS at
  `shared.vergentlms.com/api/api` is now the production path (the
  earlier "Unknown prod URL" TL;DR was stale from Round 19B).

### 2026-04-30 — Telnyx SMS MFA debug + 5/6-digit reconciliation
- Earlier commits switched SMS MFA from Twilio Verify to Telnyx
  Verify. Debugging session walked the user through Verify-Profile
  config (messaging profile attached, allowed-destinations enabled
  for US). Telnyx defaults SMS codes to 5 digits and our
  `code_length: 6` request parameter wasn't honored, so frontend
  regex relaxed to `/^\d{5,6}$/` and SMS-channel copy says "5-digit
  code" while email-channel (Cognito 6-digit) stays "6-digit".

### 2026-04-21 — In-portal Add Card (direct to Vergent)
- New `POST /api/my-cards` route on the payments Lambda. Accepts
  `{cardHolderName, cardNumber, expireMonth, expireYear, ccv,
  cardType}`, Luhn-validates + bounds-checks, forwards to Vergent
  `POST /api/CustomerPortal/Customer/Cards`. Vergent handles Repay
  tokenization server-side; our Lambda never logs PAN/CCV (only
  `last4` + brand + masked metadata).
- PCI posture: SAQ A-EP (PAN transits our HTTPS stack but is never
  stored or persisted). Quarterly ASV scans + annual AOC become a
  compliance requirement for the merchant.
- Frontend: Add Card button on `/payments.html` opens an in-page
  modal (no new tab, no redirect). Modal has name/number/exp/CVV
  with auto-formatting, Luhn check, BIN-based brand detection,
  inline errors. On success: modal closes, "Card added" toast,
  card list auto-refreshes, card immediately usable for the
  existing Pay flow.
- Routes wired via `infra/template.yaml` (new `AddCard` event on
  `PaymentsFn`) and `.github/workflows/provision-payments.yml` (new
  `POST /api/my-cards` entry). User re-runs the provisioning
  workflow once to add the new route to the live HttpApi.

### 2026-04-21 — Repay card payments (MVP: saved-card only)
- New `handlers/payments.py` exposes three routes:
  `GET /api/my-cards`, `GET /api/my-payment/loan-summary`,
  `POST /api/my-payment`. PAN is never handled on our side — we
  call Vergent's `CustomerPortal/Loans/Payments/CreditCardPayment`
  which routes to Repay and posts the payment to the loan
  atomically. Loan balance refreshes automatically.
- New Lambda `cif-portal-payments-dev` (provisioned by
  `.github/workflows/provision-payments.yml`; user runs it once).
  After provisioning, the regular `deploy.yml` updates its code on
  every push just like the other Lambdas.
- Frontend: full redesign of `payments.html` + new
  `frontend/js/payments.js` — loan summary, saved-card picker,
  amount input (defaults to amount due), error states, receipt.
  "Use a different card" button is visible but disabled with
  helper text — add-new-card flow is Phase 2, awaiting Vergent
  confirmation on Repay iframe vs hosted card page.
- Dashboard shows a one-shot "Payment of $X received" banner on
  the next page load after a successful payment, keyed off
  `sessionStorage.cif_payment_success`.

### 2026-04-21 — Dashboard polish
- Removed Vergent-internal labels from dashboard copy ("CA Payday",
  "1 Arleta, CA"); card heading reverts to "Active loan".
- Big balance now renders with cents (`$117.65` stays `$117.65`, was
  rounding to `$118`).
- `_shape_v1_loan` surfaces `apr`, `fees`, `feeBalance`,
  `numberOfPayments`, `autopay`, `loanDate`.
- Dashboard gained a 4th stat tile (Fee APR), autopay pill, payment
  progress bar, and due-date countdown.
- `get_activity` now calls v1 `GetCustomerLoanHistory` with the
  service user id captured at auth time. Defensive parsing on
  response shape.
- Added `.github/workflows/deploy.yml` (GitHub Actions). Removed the
  `--delete` flag from S3 sync after it wiped `portal.css` etc.

### 2026-04-20 — MFA SMS via Twilio Verify; branded email; SES ticket
- Swapped SMS MFA from raw Twilio Messages to Twilio Verify (no A2P
  10DLC wait). Silent retry on transient 21608 errors.
- Branded email template (bright-green header, white F monogram,
  legal footer) wired into Cognito via SES.
- AWS SES production-access ticket submitted and followed-up.

### 2026-04-19 — Signup email lock; dashboard initial wire-up
- `pre_signup.py` enforces Vergent email match before Cognito creates
  the user (`EMAIL_MISMATCH`, `MISSING_VERGENT_EMAIL`,
  `VERGENT_UNAVAILABLE`).
- `search.py` enriches single-match responses with the v1 email.
- Dashboard first-pass loads real loan data via v1
  `GET /V1/{cid}/loans`.
