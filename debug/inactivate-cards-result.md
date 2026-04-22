# Inactivate cards result

- Customer: `601488`
- Card ids: `237127,237129`
- Ran at: 2026-04-22T18:43:13Z

## Per-card results

### Card `237127`
- HTTP: `200`
- Body: `{   "id": 237127,   "company_id": 386,   "customer_id": 601488,   "card_type_id": 2,   "card_holder": "Harut Darakchyan",   "card_number": "",   "card_id": "",   "card_ref": null,   "is_eligible_for_disbursement": true,   "card_account_guid": "",   "card_guid": "",   "last_four_digits": "0295",   "product_id": 0,   "expire_month": 4,   "expire_year": 2031,   "ccv": "",   "security `

### Card `237129`
- HTTP: `200`
- Body: `{   "id": 237129,   "company_id": 386,   "customer_id": 601488,   "card_type_id": 2,   "card_holder": "Harut Darakchyan",   "card_number": "",   "card_id": "",   "card_ref": null,   "is_eligible_for_disbursement": true,   "card_account_guid": "",   "card_guid": "",   "last_four_digits": "2217",   "product_id": 0,   "expire_month": 7,   "expire_year": 2028,   "ccv": "",   "security `

## Remaining cards after inactivation
```json
[
  {
    "id": 237129,
    "card_type_id": 2,
    "card_holder": "Harut Darakchyan",
    "is_existing": false,
    "is_active": false,
    "CardProcessor": "None"
  },
  {
    "id": 237127,
    "card_type_id": 2,
    "card_holder": "Harut Darakchyan",
    "is_existing": false,
    "is_active": false,
    "CardProcessor": "None"
  }
]
```
