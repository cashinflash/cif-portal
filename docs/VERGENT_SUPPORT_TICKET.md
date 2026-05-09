# Vergent support ticket — partner-portal customer card charges

This is the draft you can paste into Vergent's support form (or
email if you have a direct contact). It lists every endpoint we've
tried, the exact errors, and what we're asking for.

---

**Subject:** Need a server-to-server way to charge a customer's saved
card from our partner portal — every documented path is broken or
unreachable for our tenant

**Tenant:** Cash in Flash (CompanyId `386`)
**Test customer:** `601488` (a real card on file, tokenized; you can
charge it successfully from your admin UI)

---

## What we're trying to do

We run a customer-facing portal at `cashinflash.com`. When a
customer is signed in, we want them to click a "Pay" button, pick
their saved card and amount, and have us charge it on the loan —
all without leaving our portal. This is what every partner customer
portal does (Brigit, Possible, EarnIn, etc.), and it's what your
own customer portal at `cashinflash.my.vergentlms.com` does for
your direct customers.

We need either:
1. **A working server-to-server charge endpoint** we can call with
   the service APIM token (`x-api-key` + JWT from `/api/authenticate`),
   OR
2. **`AuthenticateCognito` to actually mint a customer-scoped JWT**
   so we can call your existing
   `/api/CustomerPortal/Loans/Payments/CreditCardPayment` endpoint
   the way your own portal does.

Either is fine. We currently have neither.

---

## What we tried (every documented path)

### 1. v1 `POST /V1/PostCustomerLoanPayment`
Documented as the v1 charge endpoint. Body shape per the v1 PDF:
```json
{
  "CompanyId": 386,
  "StoreId": 618,
  "UserId": <our service user id>,
  "HeaderId": 4830592,
  "PaymentDate": "2026-05-07T00:00:00Z",
  "PaymentAmount": 1.00,
  "ChangeDue": 0,
  "SelectedCoupon": null,
  "CouponAmount": 0,
  "PaymentSource": 0,
  "InstrumentNumber": "",
  "PaymentMethod": { "Type": "Card", "CardId": <card_id> }
}
```

**Result:** HTTP 500 NullReferenceException at line 3413 of
`V1Controller.vb::PostCustomerLoanPayment`. Reproducible across
every body-shape variant we've tried over multiple weeks. Same
error whether the card has a Repay token or not.

```
"ExceptionMessage":"Object reference not set to an instance of an object.",
"ExceptionType":"System.NullReferenceException",
"StackTrace":"at eCashWebAPIV1.Controllers.V1Controller.PostCustomerLoanPayment(PaymentInfo value) in C:\\devops-agent-01\\_work\\301\\s\\eCashWebAPIV1\\Controllers\\V1Controller.vb:line 3413"
```

Note: your admin UI charges this same card successfully, so the
card itself isn't the problem.

### 2. v1 `POST /V1/repay/transaction/card[/sync]`
Tried this assuming it was a Repay-gateway charge endpoint based
on the path. The schema shape (from your v1 swagger UI) shows:

```json
{
  "event_meta_data": { "event_type": "...", "version": "..." },
  "event_data": {
    "request":   { "gateway_mid": ..., "amount": ..., ... },
    "timestamp": "...",
    "result":    { "result_code": ..., "auth_code": ..., "avs_result": ..., ... }
  }
}
```

The response includes `auth_code`, `pn_ref`, `avs_result` — those
are post-charge artifacts. **This appears to be a webhook receiver
that Repay calls back to Vergent after a payment is processed
elsewhere, not a charge-initiation endpoint.** Posting our charge
body to it returns "Invalid request" because it's expecting Repay's
callback envelope.

If this is meant to also accept charge-initiation payloads, please
send the schema for that mode.

### 3. v2 `POST /api/CustomerPortal/Loans/Payments/CreditCardPayment` with our service APIM token
This is the endpoint your own customer portal calls. We tried it
with the service token (`x-api-key` + JWT from `/api/authenticate`):

**Result:** HTTP 500 `DependencyResolutionException`:
```
ErrorMessage: "An exception was thrown while activating
Vergent.Lms.Api.Authorization.LoanApplicationRequirements
.CustomerPortalApplicationAccessHandler ->
Vergent.Lms.Api.CustomerPortal.Domain.Implementation.CustomerDomain ->
Vergent.Lms.Api.ExternalProvider.LegacyApi.VergentDataHelperProvider."
ErrorType: "DependencyResolutionException"
```

Looks like the DI graph requires a customer-scoped auth context
that the service token doesn't carry. Fair — but then we need a way
to MINT that customer-scoped context, see #4 and #5 below.

### 4. v2 `POST /api/CustomerPortal/AuthenticateCognito` on the APIM proxy host
Documented as the way to exchange a Cognito JWT for a Vergent
customer JWT. We send our customer's Cognito ID token (the same
JWT we identify them with via the Cognito JWT authorizer):

```
POST https://prod.apim.vergentlms.com/external/shared/api/CustomerPortal/AuthenticateCognito
Content-Type: application/json
x-api-key: <our key>
Authorization: Bearer <our APIM service JWT>

{ "jwt": "<customer's Cognito ID token>" }
```

**Result:** HTTP 500 NullReferenceException. Reproducible across
months. Same error regardless of which customer we send.

### 5. v2 `POST /api/CustomerPortal/AuthenticateCognito` on the direct host
Same call but against `https://prod.api.vergentlms.com` (the host
your own customer portal calls):

**Result:** HTTP 404. Endpoint is not exposed on the direct host.

### 6. v2 `POST /api/CustomerPortal/Authenticate` (the non-Cognito sibling)
Tested via Swagger UI on the direct host
(`https://api-external.vergentlms.com`) with a real customer-portal
username + password:

```json
POST /api/CustomerPortal/Authenticate
Content-Type: application/json

{ "userName": "<real customer username>", "password": "<real password>" }
```

**Result:** HTTP 500 `DependencyResolutionException` — same family of
error as #3, but on a different concrete type:

```json
{
  "ErrorMessage": "An exception was thrown while activating
  Vergent.Lms.Api.Customers.Domain.Implementation.CustomerDomain ->
  Vergent.Lms.Api.ExternalProvider.LegacyApi.VergentCustomerProvider.",
  "ErrorType": "DependencyResolutionException",
  "CorrelationId": "dd6ccf14-8c51-4363-855a-4c7be28fa788"
}
```

**This is critical evidence.** `/Authenticate` is a pure auth
endpoint — no customer context to resolve, no payment processor to
involve. The fact that it ALSO fails at DI activation
(`VergentCustomerProvider` can't be instantiated) for our tenant
suggests the entire `Vergent.Lms.Api.Customers.Domain` chain is
mis-configured for CompanyId `386`. Every `/api/CustomerPortal/*`
endpoint we've tried fails the same way (different concrete
types in the activation chain — `CustomerDomain` here,
`VergentDataHelperProvider` in #3 — but same root cause).

### 7. `/api/authenticate/handoff/create` `token` field
Tried using the `token` field in the handoff response as a customer
JWT for `CreditCardPayment`:

**Result:** The `token` field is a 36-character GUID, not a JWT.
When we send it as a Bearer token to `CreditCardPayment` we get the
same `DependencyResolutionException` from #3.

### 8. Customer portal sign-in (email + 2FA code)
The only customer-scoped JWT we can get is by completing the email
+ 2FA sign-in in a real browser. We can't replicate that flow from
a Lambda — we don't have the customer's email or SMS to capture
the code.

---

## What we ship today (the workaround)

Because there's no working API path, our portal can't do
in-portal card charges. As a stopgap, our "Pay" button mints a
single-use handoff URL via `POST /api/authenticate/handoff/create`
and embeds your customer portal's payment summary page
(`cashinflash.my.vergentlms.com/payment/loan/paymentsummary/<loanId>`)
in an iframe modal. The customer effectively pays inside an
embedded copy of your hosted UI.

This works but it's a worse UX than what every other partner
portal offers, and customers get prompted to sign in again
(separate username + 2FA from our portal sign-in).

## Handoff URL whitelist gaps

Three concrete issues we've hit empirically:

1. **`TargetRelativePage = "/"` redirects to `/error`.** Same for
   any non-payment-flow URL. The handoff token appears to be
   scoped to a strict whitelist of payment-flow paths only.

2. **`TargetRelativePage = "/payment/loan/makepayment/<loanId>"`
   redirects to `/error`** — even though that URL works fine when
   the customer navigates to it manually after sign-in. So the
   whitelist excludes the entry-point of your own pay flow,
   forcing us to send customers to step 2 (`selectpaymentdate`)
   or step 3 (`paymentsummary`) directly.

3. **Skipping step 1 breaks state.** When we send a customer to
   `selectpaymentdate/<loanId>` (step 2) via handoff, Vergent's
   session has no `paymentType` choice, so the subsequent summary
   page defaults to the scheduled-installment amount (e.g. $4.65)
   instead of what the customer actually wanted to pay (e.g. full
   balance $147.06). The customer can recover by clicking Home
   and navigating to Make Payment, but it's an unnecessary detour.

   **Either of these would fix it**: (a) accept `makepayment/<loanId>`
   as a valid `TargetRelativePage`, or (b) accept a query parameter
   like `?paymentType=payoff` (or `?amount=147.06`) on
   `selectpaymentdate`/`paymentsummary` so we can pre-set the
   customer's choice before they land.

4. **`TargetRelativePage` with query string redirects to `/error`.**
   `/payment/loan/paymentsummary/<loanId>?amount=147.06` fails the
   whitelist. Looks like a strict equality match rather than a
   prefix or pattern match.

---

## What we're asking for

The pattern across #3, #4, #5, and #6 is consistent: **every
`/api/CustomerPortal/*` endpoint fails at DI activation for our
tenant (CompanyId `386`)**, including pure auth endpoints with
no customer context. The same v2 surface works fine for your
own customer portal at `cashinflash.my.vergentlms.com`. Something
in our tenant's DI registration is broken.

Any one of these would unblock us — we don't need all three:

**Option A: Fix the CustomerPortal DI graph for tenant 386.** The
`VergentCustomerProvider` and `VergentDataHelperProvider`
activation failures suggest a missing tenant-level configuration
binding. Once those resolve, both `/Authenticate` and
`CreditCardPayment` should start working for us.

**Option B: Fix `AuthenticateCognito`.** Make `POST /api/CustomerPortal/
AuthenticateCognito` (on whichever host you prefer) return a
customer-scoped JWT for the customer in the supplied Cognito ID
token. Once we have that JWT we can call your existing
`CreditCardPayment` endpoint exactly the way your own portal does.

**Option C: Expose a server-to-server charge endpoint.** Anything
we can call with our service APIM token + customerId + cardId +
amount that actually charges the card and posts the payment to
the loan. The schema doesn't matter — we'll match whatever you
give us.

If there's a fourth option (a partner-portal SDK, a different
admin endpoint, etc.) we haven't found yet, please point us at
the docs.

---

## Correlation IDs / data points (in case it helps debugging)

- DependencyResolutionException correlation IDs:
  `4c8c64b7-a6b8-4690-8890-6c6fccebb7cf`,
  `48a8928a-d987-4324-8144-408f0b2792ec`,
  `dd6ccf14-8c51-4363-855a-4c7be28fa788` (this one from
  `/api/CustomerPortal/Authenticate` — pure auth, no customer
  context, still fails at DI activation)
- Test customer: `601488`
- Test loan: `4830592`
- Our service APIM `x-api-key` and JWT auth flow are working — we
  use them successfully for `/V1/GetCustomerCards`,
  `/V1/GetCustomerBanks`, `/V1/GetCustomer/{id}`, `/V1/{cid}/loans`,
  `/api/authenticate/handoff/create`, etc.

Thank you — happy to jump on a screenshare or send Postman
collections / our Lambda code if it speeds things up.
