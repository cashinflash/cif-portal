# cif-portal — Claude handoff notes

Read this FIRST before exploring. It captures the architecture, conventions,
operational gotchas, and everything built/in-flight so a fresh session can
continue without re-deriving it. (Companion notes: `cif-apply/CLAUDE.md` and
`cif-dashboard/CLAUDE.md` — read those too for anything touching the engine,
Plaid, Vergent, or the operator dashboard.)

## What this service is

`cif-portal` is the **customer-facing portal** for CashinFlash — where a
borrower signs in to: see their active loan, make a payment (debit card + ACH),
e-sign a pending loan, view loan details + documents, manage profile/cards, and
(in-flight) re-apply for a new loan. Static HTML/CSS/JS frontend + AWS Lambda
backend (Python 3.12, **stdlib + boto3 only**). No bundler, plain JS (ES5-ish,
`var`, no modules).

Live at **https://my.cashinflash.com** (custom domain, cut over 2026-06-27;
the original **https://d1zucrj1ouu3c.cloudfront.net** still resolves too). (CloudFront → S3 for the
frontend; CloudFront `/api/*` → API Gateway HTTP API `anh066l1wf` → Lambdas).

## Repos, branch, deploy

All three repos develop on branch **`claude/funny-johnson-nvssxf`**.

| Repo | Deploy | Notes |
|---|---|---|
| **cif-portal** | GitHub Actions `deploy.yml` auto-runs on push to `claude/**` or `main` | S3 sync (no --delete) + CloudFront `/*` invalidation. **Pushing the feature branch deploys it** (no merge-to-main needed). |
| **cif-apply** | Render auto-deploys `main` | Must merge to main for prod. Run via `python run_server.py` (launcher pattern). |
| **cif-dashboard** | Render auto-deploys `main` | Must merge to main for prod. |

`provision-*.yml` workflows wire AWS infra (routes, secrets, IAM, env). They're
**path-filtered** — auto-run on push only when that workflow file changes. Key
ones: `deploy.yml`, `provision-auth-onboard.yml`, `provision-auth-signup.yml`.

GitHub ops use the **GitHub MCP tools** (`mcp__github__*`) — no `gh` CLI. To
check a deploy: `mcp__github__actions_list` (list_workflow_runs / list_workflow_jobs).
The list payloads are huge — they get saved to a file; parse with python/jq.

## Cache-busting convention (IMPORTANT)

CSS + JS are referenced with `?v=YYYYMMDD<letter>` and **bumped on every change**
(the letter rolls a→b→c…). HTML itself isn't versioned (CloudFront invalidates
it). After editing `dashboard.css` you MUST bump `dashboard.css?v=` on **all 5
authed pages** (dashboard, loans, payments, profile, request-loan). Current
versions (2026-06-26):

- `dashboard.css?v=20260626j`  · `cif-esign.js?v=20260626c` · `loans.js?v=20260626h`
- `payments.js?v=20260626f` · `cif-ach.js?v=20260626c` · `dashboard.js?v=20260626c`
- `logo.png?v=hd1` (the high-res 1000×127 logo; old `Get-Fast-Cash-Loans-…png` is dead)

## Render-harness for visual verification (how we check spacing/colors)

`portal.css` is NOT in the repo (S3-only) and the live site + Vergent are
blocked by the agent proxy, so to verify CSS we render with **playwright-core +
the pre-installed Chromium** (`/opt/pw-browsers/chromium`). Pattern: inline the
real `dashboard.css` into a harness HTML, add a tiny reset + an empty
`<aside class="app-sidebar">` (so the desktop `.app-page` grid puts content in
col 2, not the 252px sidebar track), `page.setContent`, screenshot + measure
gaps via `page.evaluate`. Scripts live in the scratchpad. This is how every
spacing/color decision this session was verified — keep using it.

## Auth / Cognito / MFA (critical facts)

- **Cognito user pool: `us-east-1_U508xOs95`**. Username = email. A Cognito user
  is linked to a Vergent customer via the **`custom:vergentCustomerId`** attribute.
- **PreSignUp Lambda** (`cif-apply`? no — it's the portal's `pre_signup.py`)
  enforces: the signup email MUST equal Vergent's on-file `EmailAddr` for that
  customer id, else `EMAIL_MISMATCH`. Also blocks DUPLICATE_EMAIL /
  DUPLICATE_VERGENT_CUSTOMER / MISSING_VERGENT_EMAIL. This is why you can't
  attach a customer to an arbitrary email.
- **MFA is custom** (`backend/handlers/auth_mfa.py`), not Cognito-native:
  - login codes via **Resend** (`resend_email.py`, from `no-reply@cashinflash.com`;
    domain has SPF+DKIM). SMS via **Telnyx Verify**.
  - The **portal itself sends login codes** — the marketing/email system does not.
- Session: `frontend/js/session.js` (10-min idle, silent Cognito refresh).
- Tokens in `sessionStorage`: `cif_id_token`, `cif_access_token`, `cif_refresh_token`.

## Operational gotcha: CloudShell smart-quotes

The user's copy/paste turns straight quotes into curly “ ” which breaks `aws`
and `python`. For ANY script handed to them, use a **zero-quote base64 heredoc**:
```
base64 -d > script.py <<EOF
<base64 blob>
EOF
python3 script.py
```
The base64 alphabet has no quote chars, so it survives. We used this for
fix_login / swap_email / del / mint scripts. Generate blobs with `base64 file.py`.

## Features built this session (all cif-portal, all live)

Most live in the four big frontend files + `auth_mfa.py`. Pointers:

### E-sign / pending-signature loans (`frontend/js/cif-esign.js`, `onboard.html`-adjacent)
A loan created-but-unsigned must never read as a healthy active loan. `cif-esign.js`
(shared, loaded on dashboard/loans/payments/profile) detects pending-signature via
backend `/api/my-loans/active` (`pendingSignature` + `esign{id,signingUrl}`),
gates the card to an **orange "Pending Loan"** card, shows a "Review & sign"
strip, blocks payment. **Vergent's hosted e-sign page blocks iframing
(X-Frame-Options)** — so `openModal()` opens it in a **new tab** (`window.open`,
handle kept in `_signWin`), shows a "finish in the new tab" wait modal, **polls
`/api/my-esign/pending`** every 4s, and on completion auto-closes the tab +
redirects to `/dashboard.html`. The old custom `/api/my-esign/sign` POST does
NOT actually complete a signature — don't rely on it.

### Spacing system (pending-signature, `dashboard.css`)
The card → "Review & sign" prompt gap is a uniform **12px** on home/loans/payments
(verified via render harness). The root-cause bug was that `cif-pending-signature`
was never set on the loans page → fixed (loans.html `<head>` preflight + loans.js).
Loans pending: 12px to the prompt, then a clear break before Past loans.

### No-flash auth gate (`<head>` of every authed page)
Synchronous inline script decodes the token + redirects to `/login.html` before
paint if there's no valid session (+ `pageshow` bfcache re-check). Kills the
"flash of logged-in UI then redirect" on Back after idle logout. Also an inline
greeting setter (name + time-of-day from the token) so "Welcome back, there"
never flashes before dashboard.js fills it.

### Make-a-Payment button
`a.app-cta-primary[href*="payments.html"]` → **refined amber gradient**
(`#F59E0B → #E07C02`, dark text). (Tried navy, too heavy under the green card;
amber keeps the "tap me" warmth.)

### Payments: amount is LOCKED (no partial/custom amounts)
The pay form has **no editable amount field**. `#payAmount` is now a **hidden**
input; `setLockedAmount()` (payments.js) writes it + a read-only `[data-pay-
amount-display]` figure from the current loan. The locked value = the same
"Amount Due" the card shows: a payment-plan customer's current **installment**
(`amountDue`) or otherwise the full **balance**. Called from `renderLoanSummary`
and `resetForPayAgain`; the "Pay now $X" button + confirm modals read the same
value, so everything stays consistent. (If we ever want plan customers to pay
the full payoff instead of the installment, change `setLockedAmount` to use
`loan.balance` always.)

### Past-due styling
Card `is-pastdue` deep red `#D23636 → #8F1B1B` (was coral/pink). Pill green dot
→ **red "!" badge** (`.loan-card-pill.dash-pill--past-due::after { content:"!"; background:#dc2626 }`).
Payments page past-due detection fixed to use Vergent's `daysLate` (like Home/
Loans' `statusPillClass`), not the status string. Home desktop past-due: figures
centered + `align-self:start` so no empty band. Loans figure values unified to
one size. Loan detail summary: "Status" row removed, Payment Status → "92 Days Late".

### Loans card → details + documents
The active/past-due card on the **Loans page only** is tappable → `/loans.html?id=<loan.id>`
→ existing `showDetail()` (already loan-agnostic, shows docs for active loans).
`setupCardDetail()` in loans.js adds a centered "View details & documents" link;
the "Make your payment on time" note + divider are hidden on the loans card.
Home/Payments cards stay non-interactive by design.

### Sticky mobile top bar / misc
`.app-page` + inline `html,body` use **`overflow-x: clip`** (not `hidden`) — hidden
made the page a scroll container and broke `position:sticky` on `.app-topbar`.
Mobile top-right profile icon hidden (`.app-avatar-btn { display:none }`, redundant
with bottom nav). Disbursement cash-vs-card is NOT distinguishable from the loan
header (probed: identical), so e-sign copy is neutral "Sign to activate your loan".

## Onboarding magic-link system (the big one — see also `provision-auth-onboard.yml`)

One-click portal registration for existing customers. All in `auth_mfa.py` +
`frontend/onboard.html` + `scripts/mint_onboarding_links.py`.

- **Token**: HMAC-SHA256 signed, self-contained: `base64url(payload) "." base64url(sig)`,
  payload `{cid,email,fn,ln,exp}`. Secret in Secrets Manager
  **`cif-portal/onboard-signing-secret`** as JSON `{"secret": <hmac key>, "apiKey": <key>}`.
  Helpers: `_sign_onboard`, `_verify_onboard`, `_onboard_secret`, `_onboard_api_key`.
- **Endpoints** (in `auth_mfa.py` do_POST dispatch; routes wired by
  `provision-auth-onboard.yml`, all auth-type NONE, in-handler checks):
  - `POST /api/auth/onboard/verify {token}` → `{ok, masked, firstName, alreadyRegistered}`
  - `POST /api/auth/onboard/complete {token,password}` → creates Cognito user keyed to
    **Vergent's on-file email** (`_vergent_email_for_cid` — guarantees PreSignUp match),
    sets password, **auto-logs-in** (returns tokens). Single-use is implicit: a
    CONFIRMED account refuses re-completion.
  - `POST /api/auth/onboard/mint-link {email|customerId}` (**header `X-Api-Key`**) →
    `{url, masked, alreadyRegistered}`. The **Resend email system calls this per
    send** to drop a register link in any email — no CSV. Resolves cid from email
    via `_find_vergent_customer_id_by_email`, pulls email/first-name from Vergent
    (`_vergent_get_customer`).
- **Smart link**: `onboard.html` reads the token from the URL **fragment** (`#t=`,
  kept out of logs/Referer), calls verify; if `alreadyRegistered` → redirect to
  `/login.html`; else show set-password → complete → dashboard. So ONE link works
  for new (set password) AND existing (sign in) customers.
- **Bulk blast** (one-time, existing book): `scripts/mint_onboarding_links.py`
  over a CSV `cid,email,firstName,lastName` → `links.csv` (email,url). Reads the
  same secret. Round-trip verified against `_verify_onboard`.
- **Get the API key** (CloudShell): `aws secretsmanager get-secret-value
  --secret-id cif-portal/onboard-signing-secret --query SecretString --output text | jq -r .apiKey`

## In-flight: Fast Re-Apply (portal re-loan stream) — NOT yet built

Goal: a returning customer (no active loan) taps Apply → a **native 3-screen
portal flow** (confirm prefilled info → bank → amount → result), NOT an iframe of
apply.cashinflash.com (Plaid-in-iframe is fragile). If a **Plaid token is on
file** → "bank connected ✓" (reuse it, no re-link); else **Plaid Link** required.
Submit flows into the **same engine + Firebase + dashboard** as a normal apply.

**HARD CONSTRAINT (user is very protective): do NOT modify the live apply flow —
`apply.cashinflash.com`, its `/submit`, the engine, or the form. Add a SEPARATE,
ADDITIVE stream only.** The safe mechanism: add a new endpoint in
`cif-apply/run_server.py` (the launcher that wraps `server.py` without editing it),
reusing the existing engine + Plaid + Firebase functions. Stamp the new Firebase
report **`source: "portal_reloan"`** and show an **"RL" chip** in cif-dashboard.

Confirmed by user: (a) real app = `apply.cashinflash.com` (their form + Plaid +
engine); (b) engine runs on submit and waits for the Plaid connection (forget
bank statements); (c) the prefilled "confirm your info" fields (incl. address /
employer) are **editable** — prefill + next/next, but they can change what's
stale; (d) the amount screen is a **$100–$255 REQUEST selector** (same as the
live app) — the customer requests, the **engine decides** the approved amount.
Still assume a fresh Plaid pull on every submit. The 3 screens:
confirm-info(editable) → bank(reuse token ✓ / Plaid Link) → request amount → result.

A read-only mapping workflow (`map-reapply-foundation`, run via the Workflow
tool) was launched to map cif-apply's submit/Plaid/engine/Firebase + cif-dashboard
RL-tag spot and synthesize a surgical additive plan — check its output before
building. Reuse template for Plaid token reuse: **cif-apply `/api/refresh-from-plaid`**
(re-pulls Plaid via a stored token + re-runs the engine).

## Open go-live items

1. **Email/SMS deliverability**: confirm Resend codes land in inbox (not spam;
   consider adding DMARC) and complete **Telnyx A2P 10DLC** registration (required
   for OTP SMS; takes days). The "code didn't arrive" pain in testing was spam/
   delivery, not code.
2. **Build Fast Re-Apply** (above).
3. **Remove the temporary `?debug=signing` diagnostic** in `backend/handlers/loans.py`
   (`_debug_signing` + the `disbursementProbe`) — it served its purpose.
4. Wire the onboarding `mint-link` into the Resend email templates (the other
   Claude session that sends emails) — integration note: POST mint-link with
   `X-Api-Key`, put returned `url` on the "Register" button.

## Custom domain — my.cashinflash.com (cut over 2026-06-27)

Driven by `.github/workflows/provision-custom-domain.yml` (idempotent
workflow_dispatch). NOTE: that workflow + `set-portal-origin.yml` are
dispatched from the **default branch `claude/continue-previous-session-e2Z43`**
(workflow_dispatch only registers from the default branch; the feature
branch is ahead of it). Done:
- ACM cert (us-east-1) `…/96196a6b-3aa1-4b7e-8f8a-3da5a61439d8` — ISSUED.
- `my.cashinflash.com` + cert attached to CloudFront `EOV9K12LFKK8T` as an
  alias (ViewerCertificate = ACM, sni-only). `*.cloudfront.net` still works.
- DNS at **Namecheap**: validation CNAME (added) + final
  `my` → `d1zucrj1ouu3c.cloudfront.net` CNAME.
- `PORTAL_ORIGIN=https://my.cashinflash.com` set on all 5 Lambdas via
  `set-portal-origin.yml` → flips CORS + onboarding magic-link base.

Frontend is domain-agnostic (relative paths) so no code change was needed.
Follow-ups: repoint hardcoded `d1zucrj1ouu3c.cloudfront.net` logo/reset
links in `auth_mfa.py`/`loans.py` emails to the new domain (cosmetic, they
still work); delete the stray `provision-custom-domain.yml` copy on `main`.

## Workflow rule

Per the cif-apply/cif-dashboard CLAUDE.md: never leave a PR open — commit, (open
PR if needed), merge to main when done (those repos deploy from main via Render).
cif-portal deploys straight from the feature branch, so no PR/merge needed there.
