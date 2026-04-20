# Vergent V2 Integration — Customer Portal

How the customer-facing portal at `portal.cashinflash.com` (currently
`d1zucrj1ouu3c.cloudfront.net`) talks to Vergent to show each customer their
own loan, balance, and transaction history.

## Auth model (Round 19B)

We **don't** call `AuthenticateCognito`. Instead we use the signed-in user's
Cognito ID token to identify the customer, and Vergent's shared
`x-api-key` (from Secrets Manager) to authenticate the backend call.

### Why this works
- Round 19A's `PreSignUp` Cognito trigger links each new customer to Vergent
  and writes `custom:vergentCustomerId` onto their Cognito profile.
- That claim is signed into the ID token and surfaced to Lambda at
  `event.requestContext.authorizer.jwt.claims["custom:vergentCustomerId"]`.
- The Vergent `CustomerPortal` endpoints accept `x-api-key` + a `customerId`
  query parameter, so we can look up *this* customer's data without another
  round-trip.

### Verified token shape (production Cognito pool `us-east-1_U508xOs95`)
```json
{
  "sub": "74787448-6081-706c-3028-17ac19e8b2a4",
  "aud": "1mddi61n19hftaldt9t3r622b",
  "iss": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_U508xOs95",
  "token_use": "id",
  "email": "lhdcapital@gmail.com",
  "email_verified": true,
  "given_name": "Harut",
  "family_name": "Darakchyan",
  "custom:vergentCustomerId": "601488"
}
```

## Endpoints used

Base URL: `https://prod.apim.vergentlms.com/external/shared`
All requests send `x-api-key: <key from Secrets Manager>`.

| Purpose | Path | Query | Notes |
|---|---|---|---|
| All active + past loans for a customer | `/api/CustomerPortal/Customer/Loans/Full` | `customerId` | Primary source for the dashboard loan card. Returns principal, balance, next-payment info, status. |
| Fallback loan list | `/api/CustomerPortal/Customer/Loans` | `customerId` | Simpler shape; used if `/Loans/Full` is rejected by the tenant. |
| Transaction history | `/api/CustomerPortal/Customer/Transactions` | `customerId`, `take` | Powers "Recent activity". `take` caps to 20 in the handler. |
| Customer profile (future) | `/api/CustomerPortal/Customer/Profile` | `customerId` | For `/loans.html` detail view; not called in 19B. |
| Payment schedule (future) | `/api/CustomerPortal/Customer/Loans/{loanId}/PaymentSchedule` | — | For `/loans.html` amortization view. |

If Vergent surface differs, update `backend/handlers/loans.py` — the field
extractors use `_pick()` with multiple casings so most naming variations
already work.

## Field normalization

Vergent sometimes returns PascalCase, sometimes camelCase.
`loans.py::_shape_loan` maps either onto one canonical shape the frontend
consumes:

```json
{
  "id": "...",
  "status": "Current | Past Due | Grace | ...",
  "principal": 255.00,
  "balance": 198.42,
  "nextDueDate": "2026-05-01",
  "nextDueAmount": 50.00,
  "apr": 414.1,
  "termRemaining": 3
}
```

## Lambda contract

### `GET /api/my-loans/active`
- Authed: Cognito JWT authorizer.
- Returns `200 {"loan": <normalized loan>}` or `200 {"loan": null}` when the
  customer has no active loan (or Vergent is down — we degrade gracefully
  rather than 5xx the dashboard).

### `GET /api/my-loans/activity?limit=5`
- Authed: Cognito JWT authorizer.
- Returns `200 {"items": [...]}`. `limit` is clamped to 1–20.

## Secrets

`cif-portal/vergent/credentials` (Secrets Manager, us-east-1):
```json
{
  "xApiKey": "<rotated>",
  "logonName": "FlashAppAPI818",
  "password": "<rotated>"
}
```
The Lambda caches `xApiKey` in a module global; rotation requires a cold
restart (redeploy or version bump). `logonName`/`password` are reserved for
the `AuthenticateCognito` fallback if the x-api-key route is ever revoked.

## Failure modes and degradation

| Upstream status | Dashboard behavior | Log level |
|---|---|---|
| Vergent 200 + empty loans | "No active loan right now" empty state | info |
| Vergent 401/403 | `loan: null`, no error banner | warning |
| Vergent 5xx / timeout | `loan: null`, activity `[]` | error |
| Missing `custom:vergentCustomerId` | `loan: null` with `reason: "no-customer-id"` | warning |

The handler never returns 5xx for `/my-loans/*`; a catch-all in
`lambda_handler` converts unexpected exceptions into
`200 {"loan": null, "items": [], "error": "upstream_unavailable"}`.

## Known next steps (not in 19B)

- `/loans.html` — detail view including APR, schedule, paid-to-date.
- `/payments.html` — POST path (Repay HPP iframe or Vergent ACH).
- `/documents.html` — pull signed loan agreements / receipts via
  `/api/CustomerPortal/Customer/Documents`.
- Refresh-token flow so sessions survive > 1 hour without re-login.
