# 2FA login flow — operator notes

Customers must enter a 6-digit code sent to their email or SMS each time
they sign in. Architecture is **server-side**: the user's Cognito tokens
are issued by `AdminInitiateAuth` and held in DynamoDB until the code is
verified, so MFA cannot be bypassed by hitting Cognito directly.

## Components

| Resource | Purpose |
|---|---|
| Lambda `cif-portal-auth-mfa-dev` | Hosts `/api/auth/{login,send-code,verify-code}` |
| IAM role `cif-portal-auth-mfa-role-dev` | Cognito Admin auth, DynamoDB CRUD on the sessions table, SES + SNS publish |
| DynamoDB `cif-portal-mfa-sessions-dev` | PK=`sessionId`; TTL on `expiresAt`; rows expire 5 min after creation |
| HttpApi routes (no JWT) | `POST /api/auth/login`, `POST /api/auth/send-code`, `POST /api/auth/verify-code` |
| App client `cif-portal-spa-dev` | Now allows `ALLOW_ADMIN_USER_PASSWORD_AUTH` (in addition to existing flows) |
| SES sender | `no-reply@cashinflash.com` (hardcoded in `auth_mfa.py`; uses the DKIM-verified `cashinflash.com` domain) |
| SNS SMS | Transactional, sender id `CashFlash` (sandbox limits — see ticket) |

## Environment

`cif-portal-auth-mfa-dev` env vars:
```
COGNITO_USER_POOL_ID = us-east-1_U508xOs95
COGNITO_APP_CLIENT_ID = 1mddi61n19hftaldt9t3r622b
MFA_SESSION_TABLE     = cif-portal-mfa-sessions-dev
MFA_CODE_TTL_SECS     = 300
```

Sender is hardcoded in `auth_mfa.py` (`EMAIL_SENDER = "no-reply@cashinflash.com"`).
The `MFA_EMAIL_SENDER` env var is no longer read; if it's still set on the
deployed Lambda from a previous deploy, it's a harmless no-op and can be
deleted at leisure.

## Tweaks for testing today

1. **Verify your test customer's email in SES.** While SES is still in
   sandbox, every recipient must be on the verified-identities list.
   Run `aws ses verify-email-identity --email-address <test-customer-email>`
   (or the equivalent in the SES console: Verified identities → Create
   identity → Email address) and click the AWS verification link in
   that inbox before testing. The DKIM-verified sender domain
   (`cashinflash.com`) is already done — only the recipient needs this.
2. **Sign in normally.** Email + password works, then a channel picker
   appears. Pick "Email" to receive the code at the customer's
   on-file address.
   - If `/send-code` returns 502 with `delivery_failed_email`, the
     response body now includes `sesCode` + `sesMessage` (open
     DevTools → Network → response). That tells you whether it's the
     sandbox (recipient unverified), a sender-verification regression,
     or SES-account-paused (high bounce rate).
3. **SMS will NOT work today** — SNS sandbox restricts sends to verified
   numbers and the account has a $1/month spend cap. The picker still
   shows SMS as an option, but `/send-code` returns `delivery_failed`
   (logged in CloudWatch). See ticket B below.

## AWS support tickets to file before launch

Both are short forms in the AWS console — usually 24–48h turnaround.

### Ticket A — Move SES out of sandbox (~24h)
**Console:** SES → Account dashboard → "Request production access"
- Mail type: **Transactional**
- Website: `https://cashinflash.com`
- Use case: "We send 6-digit one-time passcodes to customers signing in
  to our customer loan portal at d1zucrj1ouu3c.cloudfront.net (later
  portal.cashinflash.com). Each code is delivered immediately on user
  action and expires in 5 minutes. We're a California-licensed lender
  (CDFPI). Email volume estimate: 200/day initially, scaling to ~1000/day."
- Compliance: confirm you only send to people who request a code
- Bounces / complaints: handled at the AWS-default rate

**Pre-req: verify a real sender domain.** Do this BEFORE filing the
ticket so AWS sees a verified domain:
```
aws ses verify-domain-identity --domain cashinflash.com
```
Then add the TXT records AWS gives you to your DNS. Once verified, set
`MFA_EMAIL_SENDER` to e.g. `noreply@cashinflash.com` and update the env
var via:
```
aws lambda update-function-configuration \
  --function-name cif-portal-auth-mfa-dev \
  --environment 'Variables={...,MFA_EMAIL_SENDER=noreply@cashinflash.com}'
```

### Ticket B — Move SNS SMS out of sandbox + raise spend limit (~24-48h)
**Console:** SNS → Mobile → SMS → "Exit SMS sandbox"
1. Increase **monthly SMS spend limit** from $1 to e.g. $200 (the limit
   you'd want for ~5,000 OTP texts/month)
2. Exit the SMS sandbox so we can text any customer (not just verified
   numbers)
3. Optional: register the **`CashFlash` sender ID** (US doesn't support
   custom sender IDs, but Canada does — leave the `SenderID` attribute
   in the code; SNS ignores it where unsupported)

**Pre-req for US:** AWS now requires **A2P 10DLC** registration for
business SMS to US numbers. Register via SNS → Mobile → Origination
numbers. Without 10DLC, US carriers will throttle / block. ~5 day
verification.

## Operational notes

- DynamoDB TTL has up to a 48h delay before deleting expired rows; we
  also enforce `expiresAt > now()` in `_load_session()` so stale rows
  are unusable even before TTL sweeps.
- Codes are stored as `sha256(code)` only; never plaintext.
- `verify-code` uses `hmac.compare_digest` to avoid timing attacks.
- 3 wrong attempts on a single session → session deleted, customer must
  re-enter their password.
- The login Lambda **always** returns the same generic message on bad
  credentials (`invalid_credentials`) — no user enumeration.

## Rollback

If MFA needs to be disabled in a hurry:
```
# Detach the routes and let the frontend hit the old InitiateAuth path.
aws apigatewayv2 get-routes --api-id anh066l1wf \
  --query 'Items[?starts_with(RouteKey,`POST /api/auth/`)].RouteId' --output text \
  | xargs -n1 -I{} aws apigatewayv2 delete-route --api-id anh066l1wf --route-id {}
# Then revert frontend to use Cognito directly:
git revert <commit-that-changed-portal.js-signIn>
```
