# Vergent Integration — Customer Portal

How the customer-facing portal at `d1zucrj1ouu3c.cloudfront.net` (later
`portal.cashinflash.com`) talks to Vergent to show each customer their own
loan, balance, and transaction history.

## TL;DR (status as of Round 19B mid)

We've discovered there are **two different Vergent APIs**, both versioned
"v1" of their respective specs but covering wildly different surface area:

| API | Purpose | Host | Spec source |
|---|---|---|---|
| **Customer Portal API** ("v2" in our naming) | Per-customer reads/writes — profile, loans, payments | `https://prod.apim.vergentlms.com/external/shared` ✅ | `docs/vergent-swagger.json` (95 paths) |
| **LMS API** ("v1" in our naming, full LMS) | Everything Cash in Flash uses internally — `/api/V1/{customerId}/...` for any customer | **Unknown prod URL** ❌ — Vergent must provide | `docs/vergent-v1/v1.pdf` (424 pages) |

Until Vergent unblocks one of two things, the dashboard cannot pull live
loan data:

1. **(Preferred) Enable AuthenticateCognito on our tenant** so we can use
   the Customer Portal API with customer-scoped JWTs.
2. Tell us the **production base URL for the LMS API** so we can use
   `/api/V1/{customerId}/loans/all` with the service token from
   `/api/authenticate`.

The Lambda is deployed and waiting — `loans.py` already implements the
AuthenticateCognito-then-call-Customer-Portal flow. The moment Vergent
flips switch (1) it starts returning real data without a code change.

## What we already know works

### `POST /api/authenticate` (service-account login)
- URL: `https://prod.apim.vergentlms.com/external/shared/api/authenticate`
- Body (camelCase, returned by `application/json`):
  ```json
  { "userName": "FlashAppAPI818", "password": "<from secret>" }
  ```
- Headers: `x-api-key: <from secret>`
- Response (note: response body is itself a JSON-encoded string — parse
  twice):
  ```json
  {
    "companyId": "386",
    "id": "8434",            // SERVICE user id, not a customer id
    "roleId": "1467",
    "auth_token": "eyJhbGc..."  // ~5860-char JWT
  }
  ```
- Token works as `Authorization: Bearer <auth_token>` for every other
  endpoint we've tested.

### `GET /api/CustomerPortal/Customer/SearchByEmail/{email}`
Returns the customer's `mobileProfileId` (e.g. `customer@example.com` →
`6007`). Used to confirm portal-account existence pre-login.

### `POST /api/CustomerPortal/Customer/Search`
Used by Round 14's signup flow. Body shape lives in
`backend/handlers/search.py`. Already in production.

## What's broken (and why)

### `POST /api/CustomerPortal/AuthenticateCognito` → 500 NullReferenceException
Vergent crashes internally on **both** dummy and real Cognito JWTs. Same
correlation pattern every time:
```
{ "ErrorMessage": "Object reference not set to an instance of an object.",
  "ErrorType": "NullReferenceException" }
```
Cause (inferred): no Cognito issuer registered for our tenant on the
Vergent side, so their lookup of "which Cognito pool do I trust?" returns
null and the `.NET` code null-refs.

**Unblock**: Vergent registers our Cognito pool. Need:
- **Issuer**: `https://cognito-idp.us-east-1.amazonaws.com/us-east-1_U508xOs95`
- **Audience (App Client ID)**: `1mddi61n19hftaldt9t3r622b`
- **Company ID**: `386`
- **User-matching claim**: `email`

### `GET /api/CustomerPortal/Customer/Loans/Full` etc. with **service** token → "Sequence contains no elements"
The endpoint reads the JWT's `id` claim and looks it up as a customer
`mobileProfileId`. Our service token has `id = 8434` (the FlashAppAPI818
user), not a customer's profile id. Trace:
```
Vergent.Database.Implementation.Repository.MobileProfileRepository
    .GetCustomerByMobileProfileId(UInt32 companyId, UInt32 mobileProfileId, ...)
    → System.Linq.Enumerable.First → ThrowNoElementsException
```
This confirms: **Customer Portal endpoints require customer-scoped JWTs**,
not the service token. Service token + customerId-in-URL is not a thing on
this API.

### LMS v1 paths (`/api/V1/{customerId}/loans/all`) → 404 at our APIM
The APIM gateway at `prod.apim.vergentlms.com/external/shared` only routes
the Customer Portal API. The LMS v1 paths simply aren't exposed there.
Tried these alternates, all dead:
- `prod.apim.vergentlms.com/external/(internal|v1|legacy|cashinflash)`
- `prod.apim.vergentlms.com/(api|v1)`
- `prod-api.vergentlms.com`, `api.vergentlms.com`, `prod.vergentlms.com`
- `training.vergentlms.com/api/api/...` → reachable but rejects our prod
  credentials (separate user store)

## Endpoint inventory (kept for when one of the two paths unblocks)

### Customer Portal (Vergent Public API — `prod.apim.vergentlms.com/external/shared`)
Auth on these requires Bearer token from `AuthenticateCognito` once enabled.

| Verb | Path | Use |
|---|---|---|
| POST | `/api/CustomerPortal/AuthenticateCognito` | Exchange Cognito JWT → CP token |
| GET  | `/api/CustomerPortal/Customer/Profile` | Profile card (name, email, phones, addresses, cards) |
| GET  | `/api/CustomerPortal/Customer/Loans/Full` | All loans w/ detail (`FullProcessInfoModel`) |
| GET  | `/api/CustomerPortal/Loans` | Open loans only (`LoanCardModel[]`) |
| GET  | `/api/CustomerPortal/Loans/{loanId}/Transactions` | Loan-scoped transaction history |
| GET  | `/api/CustomerPortal/Loans/{loanId}/Source/{source}/PaymentSchedule` | Amortization schedule |
| GET  | `/api/CustomerPortal/Loans/{loanId}/Documents/ContractsAndReceipts` | Loan docs |
| GET  | `/api/CustomerPortal/Customer/Documents` | All customer docs |
| GET  | `/api/CustomerPortal/Customer/Documents/{documentId}/Url` | Signed download URL |
| GET  | `/api/CustomerPortal/Customer/Addresses` | Address list |
| POST | `/api/CustomerPortal/Customer/Address/Save` | Add/update address |
| GET  | `/api/CustomerPortal/Customer/Cards` | Card list |
| POST | `/api/CustomerPortal/Customer/Cards` | Save new card |
| POST | `/api/CustomerPortal/Loans/Payments/CreditCardPayment` | Card payment on a loan |

### LMS API (Vergent v1 — host TBD)
Pre-built shopping list once we have the URL. Auth: service `Token` header.

| Verb | Path | Use |
|---|---|---|
| POST | `/api/authenticate` | LogonName/Password → service token (already works at APIM) |
| GET  | `/api/V1/{customerId}/loans/all` | All loans for a customer |
| GET  | `/api/V1/{customerId}/loans` | Open loans (filterable: statusIds, numresults, includePrevious) |
| GET  | `/api/V1/GetCustomer/{id}` | Customer profile |
| GET  | `/api/V1/GetCustomerData/{id}` | Full demographics |
| GET  | `/api/V1/GetCustomerPhones` (+POST/PUT) | Phone CRUD |
| GET  | `/api/V1/GetAddresses` (+POST/PUT) | Address CRUD |
| **PUT** | **`/api/V1/PutCustomerEmail`** | **Email update — answers the user's specific ask** |
| POST | `/api/V1/customer/{id}/communication/{type}/validate/{cell}` | Send SMS PIN |
| POST | `/api/V1/customer/{id}/communication/{type}/validate/{cell}/confirm/{code}` | Verify SMS PIN |
| POST | `/api/V1/customer/{id}/communication/trigger/emailchanged/{newEmail}` | Trigger email-change notification |
| POST | `/api/V1/PostBankPayment` | Initiate bank payment |
| GET  | `/api/V1/customer/{id}/docs/loan/{loanHeaderId}` | Loan documents |

## Lambda-side contracts

### `GET /api/my-loans/active` (Cognito-authed)
- Pulls the raw Cognito ID token from `Authorization: Bearer …`
- Calls `POST /api/CustomerPortal/AuthenticateCognito` with `{"jwt": "..."}`
- Caches the returned CP token per `sub` for 5 minutes
- Calls `GET /api/CustomerPortal/Loans` (auto-filtered to open loans by Vergent)
- Shapes first card to `{principal, balance, nextDueDate, nextDueAmount, status, …}`
- Returns `200 {"loan": …}` (or `null` if upstream is down — never 5xx the dashboard)

### `GET /api/my-loans/activity?limit=5` (Cognito-authed)
- Same auth dance, then `GET /api/CustomerPortal/Loans/{loanId}/Transactions`
- Returns `200 {"items": [{date, description, amount, direction, balance, cardLast4}]}`

## Secrets

`cif-portal/vergent/credentials` (Secrets Manager, `us-east-1`):
```json
{
  "xApiKey": "<rotated>",
  "logonName": "FlashAppAPI818",
  "password": "<rotated>"
}
```
- `xApiKey` cached in a module global; rotation = redeploy or version bump.
- `logonName`/`password` used by the LMS-API path (when we get the URL) for
  `/api/authenticate`.

## Failure modes and degradation

| Upstream | Dashboard behavior | Log level |
|---|---|---|
| Vergent 200 + empty loans | "No active loan right now" empty state | info |
| Vergent 401/403 | `loan: null`, no banner | warning |
| Vergent 5xx / timeout | `loan: null`, activity `[]` | error |
| AuthenticateCognito 500 (current state) | `loan: null, reason: "auth-exchange-failed"` | warning |
| Missing id token / sub | `loan: null, reason: "no-id-token"` | warning |

The handler never returns 5xx for `/my-loans/*`; a top-level catch in
`lambda_handler` converts unexpected exceptions into
`200 {"loan": null, "items": [], "error": "upstream_unavailable"}`.

## Open questions for Vergent

Send these in one email — any single answer unblocks us. Attach
`docs/vergent-instructions.pdf` (the Customer Onboarding API Reference
Vergent sent us on 4/16/26) as supporting context for #2.

1. Please enable `POST /api/CustomerPortal/AuthenticateCognito` for company
   386. Issuer + audience + claim above. Current 500 on every call.
2. **Production base URL for the v1 LMS API** — the host that serves the
   endpoints your Customer Onboarding guide documents
   (`/api/V1/PostCustomerData`, `/api/V1/GetCustomerData/{id}`,
   `/api/v1/GetCustomers`, `/api/v1/customer/{customerId}/upload`, etc.).
   Our service user `FlashAppAPI818` authenticates fine at
   `prod.apim.vergentlms.com/external/shared/api/authenticate` but those
   v1 paths 404 there, and `training.vergentlms.com/api/api/...` returns
   401 on our prod credentials (implying training is a separate user
   store). If our existing creds aren't valid on the v1 prod host,
   please provision new creds tied to company 386.
3. (Optional / cleanest) Expose v1 routes under our existing APIM prefix
   `prod.apim.vergentlms.com/external/shared` so we use one host + one
   credential set for everything.

## What the Customer Onboarding doc gave us (schemas we'll need later)

Stored at `docs/vergent-instructions.pdf`. Useful once unblocked:

### `POST /api/V1/PostCustomerData` body shape
```json
{
  "cust": {
    "CustomerType": 1,        // 1=Individual, 2=Business
    "FirstName": "...", "LastName": "...", "MiddleName": "...", "Suffix": "",
    "NinType": 1,             // 1=SSN, 2=SIN, 3=EIN, 4=ALT
    "Ssn": "...", "BirthDate": "MM/DD/YYYY",
    "EmailAddr": "...", "StoreId": 0, "DBA": ""
  },
  "custEmps":      [{"PayAmount": 0, "PrevPayDate": "...", "PayFreqId": 0,
                     "NextPayDate": "...", "Name": "...", "IsDirectDeposit": true,
                     "DateEmployed": "...", "EmpType": 0, "IsPrimary": true}],
  "custAddresses": [{"type_id": 0, "addr1": "...", "city": "...",
                     "state_id": 0, "zip": "...", "abbrev": "TX",
                     "status": 1, "IsPrimary": true}],
  "custPhones":    [{"type_id": 0, "number": "...", "is_primary": true,
                     "IsPrimary": true}],
  "custBanks":     [{"Name": "...", "RoutingNum": "...", "AccountNum": "...",
                     "IsDirectDep": true, "TypeId": 0, "IsPrimary": true}],
  "custIds":       [{"type_id": "613", "id_issued_on_date": "...",
                     "id_num": "...", "id_zip": "...", "id_state_id": "99",
                     "id_expiration_date": "...", "status": 1}]
}
```

### Option-class lookups (cache these; they rarely change)
- `GET /api/V1/GetOptionClassesAsync` → classes for address types, phone
  types, bank types, id types, etc.
- `GET /api/V1/GetOptionsByClassAsync?classId={id}` → items inside a
  class
- `GET /api/V1/GetStates` → state ids for `state_id` + `abbrev`
- `GET /api/V1/GetCompanyPayFreq` → pay frequency ids for `PayFreqId`
- `GET /api/CompanyInfo/GetStores` → store ids for `StoreId`
- `GET /api/V1/GetLoanModels` → loan product ids for originations

### Customer lookup
- `GET /api/v1/GetCustomers?name=&phone=&idnum=&email=&birthDate=` →
  fuzzy search, returns array
- `GET /api/V1/GetCustomerData/{customerId}` → single record, same shape
  as `PostCustomerData` body

### Documents
- `POST /api/v1/customer/{customerId}/upload` — multipart:
  - `file`: the bytes
  - application/json part: `{"Title": "Document.pdf"}`
- `POST /api/v1/customer/{customerId}/store` — Vergent fetches the doc
  from a URL we provide:
  ```json
  {
    "Filename": "test.pdf",
    "Url": "https://our-bucket/…",
    "UrlHeaders": [{"Key": "...", "Value": "..."}],
    "Title": "Test Document"
  }
  ```
- Response `{Id, DownloadUrl, …}`. DownloadUrl points back to
  `host/api/api/V1/docs/{id}/download`.

### Vehicle / personal property
`POST` with `prop_type: "2"` (vehicle), `vehicle_type: P|C|M|R`, and a
bunch of VIN/blackbook fields.

