# Payments Lambda logs

- Function: `cif-portal-payments-dev`
- Window: last 12 minute(s)
- Filter: `(none)`
- Captured at: 2026-06-16T21:07:45Z

## 56 event(s)

```
20:57:14  INIT_START Runtime Version: python:3.12.mainlinev2.v11	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:bec1042407ffdf4a1e2261cba8ed01949f62579da0d7ee83345b26dd8890eef8
20:57:14  INIT_START Runtime Version: python:3.12.mainlinev2.v11	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:bec1042407ffdf4a1e2261cba8ed01949f62579da0d7ee83345b26dd8890eef8
20:57:15  START RequestId: 61ed03e3-6b48-4e2c-ac96-a8d9609a0edd Version: $LATEST
20:57:15  [payments] entry path='/dev/api/my-cards' method='GET'
20:57:15  START RequestId: 4c99fb25-9715-4e95-8bcc-0a9cebf4f135 Version: $LATEST
20:57:15  [payments] entry path='/dev/api/my-payment/loan-summary' method='GET'
20:57:15  [INFO]	2026-06-16T20:57:15.752Z	61ed03e3-6b48-4e2c-ac96-a8d9609a0edd	v1 service Token cached (3600s) userId=8434
20:57:15  [INFO]	2026-06-16T20:57:15.772Z	4c99fb25-9715-4e95-8bcc-0a9cebf4f135	v1 service Token cached (3600s) userId=8434
20:57:15  [INFO]	2026-06-16T20:57:15.841Z	61ed03e3-6b48-4e2c-ac96-a8d9609a0edd	GetCustomerCards cid=601488 count=5 cards=[{'id': 237669, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237131, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237130, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237129, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 1}, {'id': 237127, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}]
20:57:15  [INFO]	2026-06-16T20:57:15.892Z	61ed03e3-6b48-4e2c-ac96-a8d9609a0edd	GetCustomerCardTypes loaded: {3: 'AMEX', 4: 'Discover', 7: 'Insight', 1: 'MasterCard', 9: 'Netspend DDA', 8: 'Netspend GPR', 2: 'Visa'}
20:57:15  END RequestId: 61ed03e3-6b48-4e2c-ac96-a8d9609a0edd
20:57:15  REPORT RequestId: 61ed03e3-6b48-4e2c-ac96-a8d9609a0edd	Duration: 602.11 ms	Billed Duration: 1230 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	Init Duration: 627.69 ms	
20:57:18  END RequestId: 4c99fb25-9715-4e95-8bcc-0a9cebf4f135
20:57:18  REPORT RequestId: 4c99fb25-9715-4e95-8bcc-0a9cebf4f135	Duration: 3279.23 ms	Billed Duration: 3916 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	Init Duration: 636.68 ms	
20:57:34  START RequestId: edb5bd1e-cae9-4d95-8d30-b13121e0caee Version: $LATEST
20:57:34  [payments] entry path='/dev/api/my-cards' method='POST'
20:57:34  [INFO]	2026-06-16T20:57:34.401Z	edb5bd1e-cae9-4d95-8d30-b13121e0caee	GetCustomerCardTypes loaded: {3: 'AMEX', 4: 'Discover', 7: 'Insight', 1: 'MasterCard', 9: 'Netspend DDA', 8: 'Netspend GPR', 2: 'Visa'}
20:57:34  [WARNING]	2026-06-16T20:57:34.560Z	edb5bd1e-cae9-4d95-8d30-b13121e0caee	Vergent POST https://api.repayonline.com/rgapi/v1.0/customers/601488/cardtokens -> 404: {
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
20:57:34  [WARNING]	2026-06-16T20:57:34.560Z	edb5bd1e-cae9-4d95-8d30-b13121e0caee	repay cardtoken cid=601488 status=404 body_head={
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
20:57:34  [WARNING]	2026-06-16T20:57:34.560Z	edb5bd1e-cae9-4d95-8d30-b13121e0caee	save-card tokenize failed cid=601488 reason=repay_http_404
20:57:34  END RequestId: edb5bd1e-cae9-4d95-8d30-b13121e0caee
20:57:34  REPORT RequestId: edb5bd1e-cae9-4d95-8d30-b13121e0caee	Duration: 234.26 ms	Billed Duration: 235 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	
20:57:38  START RequestId: 01bcf494-d7a4-4292-87c4-ffa210614a8a Version: $LATEST
20:57:38  [payments] entry path='/dev/api/my-cards' method='POST'
20:57:38  [WARNING]	2026-06-16T20:57:38.239Z	01bcf494-d7a4-4292-87c4-ffa210614a8a	Vergent POST https://api.repayonline.com/rgapi/v1.0/customers/601488/cardtokens -> 404: {
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
20:57:38  [WARNING]	2026-06-16T20:57:38.240Z	01bcf494-d7a4-4292-87c4-ffa210614a8a	repay cardtoken cid=601488 status=404 body_head={
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
20:57:38  [WARNING]	2026-06-16T20:57:38.240Z	01bcf494-d7a4-4292-87c4-ffa210614a8a	save-card tokenize failed cid=601488 reason=repay_http_404
20:57:38  END RequestId: 01bcf494-d7a4-4292-87c4-ffa210614a8a
20:57:38  REPORT RequestId: 01bcf494-d7a4-4292-87c4-ffa210614a8a	Duration: 140.96 ms	Billed Duration: 141 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	
21:03:59  INIT_START Runtime Version: python:3.12.mainlinev2.v11	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:bec1042407ffdf4a1e2261cba8ed01949f62579da0d7ee83345b26dd8890eef8
21:03:59  INIT_START Runtime Version: python:3.12.mainlinev2.v11	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:bec1042407ffdf4a1e2261cba8ed01949f62579da0d7ee83345b26dd8890eef8
21:04:00  START RequestId: 93df29a3-667d-46de-b035-2a5eb7934343 Version: $LATEST
21:04:00  [payments] entry path='/dev/api/my-payment/loan-summary' method='GET'
21:04:00  START RequestId: 3a8dcec2-00b6-45be-b4c9-ca85a51f96c3 Version: $LATEST
21:04:00  [payments] entry path='/dev/api/my-cards' method='GET'
21:04:00  [INFO]	2026-06-16T21:04:00.702Z	93df29a3-667d-46de-b035-2a5eb7934343	v1 service Token cached (3600s) userId=8434
21:04:00  [INFO]	2026-06-16T21:04:00.781Z	3a8dcec2-00b6-45be-b4c9-ca85a51f96c3	v1 service Token cached (3600s) userId=8434
21:04:00  [INFO]	2026-06-16T21:04:00.874Z	3a8dcec2-00b6-45be-b4c9-ca85a51f96c3	GetCustomerCards cid=601488 count=5 cards=[{'id': 237669, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237131, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237130, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237129, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 1}, {'id': 237127, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}]
21:04:00  [INFO]	2026-06-16T21:04:00.927Z	3a8dcec2-00b6-45be-b4c9-ca85a51f96c3	GetCustomerCardTypes loaded: {3: 'AMEX', 4: 'Discover', 7: 'Insight', 1: 'MasterCard', 9: 'Netspend DDA', 8: 'Netspend GPR', 2: 'Visa'}
21:04:00  END RequestId: 3a8dcec2-00b6-45be-b4c9-ca85a51f96c3
21:04:00  REPORT RequestId: 3a8dcec2-00b6-45be-b4c9-ca85a51f96c3	Duration: 544.35 ms	Billed Duration: 1097 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	Init Duration: 552.09 ms	
21:04:03  END RequestId: 93df29a3-667d-46de-b035-2a5eb7934343
21:04:03  REPORT RequestId: 93df29a3-667d-46de-b035-2a5eb7934343	Duration: 3426.32 ms	Billed Duration: 3932 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	Init Duration: 505.50 ms	
21:04:21  START RequestId: 742066e2-1be8-4fea-b6b3-158a2850ff0b Version: $LATEST
21:04:21  [payments] entry path='/dev/api/my-cards' method='POST'
21:04:21  [INFO]	2026-06-16T21:04:21.139Z	742066e2-1be8-4fea-b6b3-158a2850ff0b	GetCustomerCardTypes loaded: {3: 'AMEX', 4: 'Discover', 7: 'Insight', 1: 'MasterCard', 9: 'Netspend DDA', 8: 'Netspend GPR', 2: 'Visa'}
21:04:22  [WARNING]	2026-06-16T21:04:22.144Z	742066e2-1be8-4fea-b6b3-158a2850ff0b	cardsafe StoreCard cid=601488 no token: <?xml version="1.0" encoding="utf-8"?> <Response xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="https://api.repayonline.com/ws/">   <Result
21:04:22  [WARNING]	2026-06-16T21:04:22.145Z	742066e2-1be8-4fea-b6b3-158a2850ff0b	save-card tokenize failed cid=601488 reason=cardsafe_no_token
21:04:22  END RequestId: 742066e2-1be8-4fea-b6b3-158a2850ff0b
21:04:22  REPORT RequestId: 742066e2-1be8-4fea-b6b3-158a2850ff0b	Duration: 1110.98 ms	Billed Duration: 1111 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	
21:04:26  START RequestId: f7bf3ab4-0e29-451b-970d-a4af96c5c6e1 Version: $LATEST
21:04:26  [payments] entry path='/dev/api/my-cards' method='POST'
21:04:27  [WARNING]	2026-06-16T21:04:27.271Z	f7bf3ab4-0e29-451b-970d-a4af96c5c6e1	cardsafe StoreCard cid=601488 no token: <?xml version="1.0" encoding="utf-8"?> <Response xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="https://api.repayonline.com/ws/">   <Result
21:04:27  [WARNING]	2026-06-16T21:04:27.271Z	f7bf3ab4-0e29-451b-970d-a4af96c5c6e1	save-card tokenize failed cid=601488 reason=cardsafe_no_token
21:04:27  END RequestId: f7bf3ab4-0e29-451b-970d-a4af96c5c6e1
21:04:27  REPORT RequestId: f7bf3ab4-0e29-451b-970d-a4af96c5c6e1	Duration: 975.45 ms	Billed Duration: 976 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	
```
