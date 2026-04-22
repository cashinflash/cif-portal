# Inactivate cards result

- Customer: `601488`
- Card ids: `237127,237129`
- Ran at: 2026-04-22T18:42:09Z

## Per-card results

### Card `237127`
- HTTP: `500`
- Body: `{   "Message": "An error has occurred.",   "ExceptionMessage": "Object reference not set to an instance of an object.",   "ExceptionType": "System.NullReferenceException",   "StackTrace": "   at eCashWebAPIV1.Controllers.V1Controller.VB$StateMachine_66_PutCustomerInactivateCard.MoveNext() in C:\\devops-agent-01\\_work\\281\\s\\eCashWebAPIV1\\Controllers\\V1Controller.vb:line 2432\r\n--- End of `

### Card `237129`
- HTTP: `500`
- Body: `{   "Message": "An error has occurred.",   "ExceptionMessage": "Object reference not set to an instance of an object.",   "ExceptionType": "System.NullReferenceException",   "StackTrace": "   at eCashWebAPIV1.Controllers.V1Controller.VB$StateMachine_66_PutCustomerInactivateCard.MoveNext() in C:\\devops-agent-01\\_work\\281\\s\\eCashWebAPIV1\\Controllers\\V1Controller.vb:line 2432\r\n--- End of `

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
