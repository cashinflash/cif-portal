# Payments Lambda logs

- Function: `cif-portal-payments-dev`
- Window: last 20 minute(s)
- Filter: `(none)`
- Captured at: 2026-06-16T20:40:17Z

## 63 event(s)

```
20:32:17  INIT_START Runtime Version: python:3.12.mainlinev2.v11	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:bec1042407ffdf4a1e2261cba8ed01949f62579da0d7ee83345b26dd8890eef8
20:32:17  INIT_START Runtime Version: python:3.12.mainlinev2.v11	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:bec1042407ffdf4a1e2261cba8ed01949f62579da0d7ee83345b26dd8890eef8
20:32:18  START RequestId: 9a0f913a-f9df-489a-a89f-bcc59cd8a5a3 Version: $LATEST
20:32:18  [payments] entry path='/dev/api/my-payment/loan-summary' method='GET'
20:32:18  START RequestId: 76c194a7-9fc8-42ee-ba7e-d52dc6995a70 Version: $LATEST
20:32:18  [payments] entry path='/dev/api/my-cards' method='GET'
20:32:18  [INFO]	2026-06-16T20:32:18.483Z	9a0f913a-f9df-489a-a89f-bcc59cd8a5a3	v1 service Token cached (3600s) userId=8434
20:32:18  [INFO]	2026-06-16T20:32:18.685Z	76c194a7-9fc8-42ee-ba7e-d52dc6995a70	v1 service Token cached (3600s) userId=8434
20:32:18  [INFO]	2026-06-16T20:32:18.767Z	76c194a7-9fc8-42ee-ba7e-d52dc6995a70	GetCustomerCards cid=601488 count=5 cards=[{'id': 237669, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237131, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237130, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237129, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 1}, {'id': 237127, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}]
20:32:18  [INFO]	2026-06-16T20:32:18.849Z	76c194a7-9fc8-42ee-ba7e-d52dc6995a70	GetCustomerCardTypes loaded: {3: 'AMEX', 4: 'Discover', 7: 'Insight', 1: 'MasterCard', 9: 'Netspend DDA', 8: 'Netspend GPR', 2: 'Visa'}
20:32:18  END RequestId: 76c194a7-9fc8-42ee-ba7e-d52dc6995a70
20:32:18  REPORT RequestId: 76c194a7-9fc8-42ee-ba7e-d52dc6995a70	Duration: 620.97 ms	Billed Duration: 1268 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	Init Duration: 646.30 ms	
20:32:22  END RequestId: 9a0f913a-f9df-489a-a89f-bcc59cd8a5a3
20:32:22  REPORT RequestId: 9a0f913a-f9df-489a-a89f-bcc59cd8a5a3	Duration: 4205.36 ms	Billed Duration: 4685 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	Init Duration: 478.87 ms	
20:33:17  START RequestId: 8242e864-6cfe-4dc2-85a0-7e915f64794e Version: $LATEST
20:33:17  [payments] entry path='/dev/api/my-payment/loan-summary' method='GET'
20:33:17  START RequestId: 81282337-b257-4b97-95a1-d1020a0d19bd Version: $LATEST
20:33:17  [payments] entry path='/dev/api/my-cards' method='GET'
20:33:17  [INFO]	2026-06-16T20:33:17.520Z	81282337-b257-4b97-95a1-d1020a0d19bd	GetCustomerCards cid=601488 count=5 cards=[{'id': 237669, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237131, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237130, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237129, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 1}, {'id': 237127, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}]
20:33:17  END RequestId: 81282337-b257-4b97-95a1-d1020a0d19bd
20:33:17  REPORT RequestId: 81282337-b257-4b97-95a1-d1020a0d19bd	Duration: 103.02 ms	Billed Duration: 104 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	
20:33:20  END RequestId: 8242e864-6cfe-4dc2-85a0-7e915f64794e
20:33:20  REPORT RequestId: 8242e864-6cfe-4dc2-85a0-7e915f64794e	Duration: 3316.78 ms	Billed Duration: 3317 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	
20:33:32  START RequestId: e1b46db8-17e7-4e24-b4b1-80cdee98bfb9 Version: $LATEST
20:33:32  [payments] entry path='/dev/api/my-payment/loan-summary' method='GET'
20:33:32  START RequestId: 44228558-9874-4b56-a909-1085bbc25a18 Version: $LATEST
20:33:32  [payments] entry path='/dev/api/my-cards' method='GET'
20:33:32  [INFO]	2026-06-16T20:33:32.890Z	44228558-9874-4b56-a909-1085bbc25a18	GetCustomerCards cid=601488 count=5 cards=[{'id': 237669, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237131, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237130, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237129, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 1}, {'id': 237127, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}]
20:33:32  END RequestId: 44228558-9874-4b56-a909-1085bbc25a18
20:33:32  REPORT RequestId: 44228558-9874-4b56-a909-1085bbc25a18	Duration: 104.00 ms	Billed Duration: 105 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	
20:33:36  END RequestId: e1b46db8-17e7-4e24-b4b1-80cdee98bfb9
20:33:36  REPORT RequestId: e1b46db8-17e7-4e24-b4b1-80cdee98bfb9	Duration: 3362.73 ms	Billed Duration: 3363 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	
20:34:07  START RequestId: 5dcd823e-08ab-4348-a527-50d211a3cda2 Version: $LATEST
20:34:07  [payments] entry path='/dev/api/my-payment/loan-summary' method='GET'
20:34:07  START RequestId: c080fc0d-af9f-4cf2-a681-49f00dd842ea Version: $LATEST
20:34:07  [payments] entry path='/dev/api/my-cards' method='GET'
20:34:07  [INFO]	2026-06-16T20:34:07.844Z	c080fc0d-af9f-4cf2-a681-49f00dd842ea	GetCustomerCards cid=601488 count=5 cards=[{'id': 237669, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237131, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237130, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237129, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 1}, {'id': 237127, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}]
20:34:07  END RequestId: c080fc0d-af9f-4cf2-a681-49f00dd842ea
20:34:07  REPORT RequestId: c080fc0d-af9f-4cf2-a681-49f00dd842ea	Duration: 103.20 ms	Billed Duration: 104 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	
20:34:10  END RequestId: 5dcd823e-08ab-4348-a527-50d211a3cda2
20:34:10  REPORT RequestId: 5dcd823e-08ab-4348-a527-50d211a3cda2	Duration: 2750.93 ms	Billed Duration: 2751 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	
20:34:35  START RequestId: 9193319c-c578-4dbc-8d59-29ed032a9e83 Version: $LATEST
20:34:35  [payments] entry path='/dev/api/my-cards' method='POST'
20:34:35  [INFO]	2026-06-16T20:34:35.884Z	9193319c-c578-4dbc-8d59-29ed032a9e83	GetCustomerCardTypes loaded: {3: 'AMEX', 4: 'Discover', 7: 'Insight', 1: 'MasterCard', 9: 'Netspend DDA', 8: 'Netspend GPR', 2: 'Visa'}
20:34:36  [WARNING]	2026-06-16T20:34:36.133Z	9193319c-c578-4dbc-8d59-29ed032a9e83	Vergent POST https://api.repayonline.com/rgapi/v1.0/customers/601488/cardtokens -> 404: {
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
20:34:36  [WARNING]	2026-06-16T20:34:36.133Z	9193319c-c578-4dbc-8d59-29ed032a9e83	repay cardtoken cid=601488 status=404 body_head={
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
20:34:36  [WARNING]	2026-06-16T20:34:36.133Z	9193319c-c578-4dbc-8d59-29ed032a9e83	save-card tokenize failed cid=601488 reason=repay_http_404
20:34:36  END RequestId: 9193319c-c578-4dbc-8d59-29ed032a9e83
20:34:36  REPORT RequestId: 9193319c-c578-4dbc-8d59-29ed032a9e83	Duration: 315.11 ms	Billed Duration: 316 ms	Memory Size: 256 MB	Max Memory Used: 106 MB	
20:34:41  START RequestId: 8a6cfb5c-7bd9-4a9b-a40c-ca1350233123 Version: $LATEST
20:34:41  [payments] entry path='/dev/api/my-cards' method='POST'
20:34:41  [WARNING]	2026-06-16T20:34:41.323Z	8a6cfb5c-7bd9-4a9b-a40c-ca1350233123	Vergent POST https://api.repayonline.com/rgapi/v1.0/customers/601488/cardtokens -> 404: {
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
20:34:41  [WARNING]	2026-06-16T20:34:41.323Z	8a6cfb5c-7bd9-4a9b-a40c-ca1350233123	repay cardtoken cid=601488 status=404 body_head={
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
20:34:41  [WARNING]	2026-06-16T20:34:41.323Z	8a6cfb5c-7bd9-4a9b-a40c-ca1350233123	save-card tokenize failed cid=601488 reason=repay_http_404
20:34:41  END RequestId: 8a6cfb5c-7bd9-4a9b-a40c-ca1350233123
20:34:41  REPORT RequestId: 8a6cfb5c-7bd9-4a9b-a40c-ca1350233123	Duration: 116.73 ms	Billed Duration: 117 ms	Memory Size: 256 MB	Max Memory Used: 106 MB	
20:36:12  START RequestId: 75d95de8-6a62-4d4f-aa34-e4a4c404fcb2 Version: $LATEST
20:36:12  [payments] entry path='/dev/api/my-cards' method='POST'
20:36:12  [WARNING]	2026-06-16T20:36:12.388Z	75d95de8-6a62-4d4f-aa34-e4a4c404fcb2	Vergent POST https://api.repayonline.com/rgapi/v1.0/customers/601488/cardtokens -> 404: {
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
20:36:12  [WARNING]	2026-06-16T20:36:12.388Z	75d95de8-6a62-4d4f-aa34-e4a4c404fcb2	repay cardtoken cid=601488 status=404 body_head={
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
20:36:12  [WARNING]	2026-06-16T20:36:12.388Z	75d95de8-6a62-4d4f-aa34-e4a4c404fcb2	save-card tokenize failed cid=601488 reason=repay_http_404
20:36:12  END RequestId: 75d95de8-6a62-4d4f-aa34-e4a4c404fcb2
20:36:12  REPORT RequestId: 75d95de8-6a62-4d4f-aa34-e4a4c404fcb2	Duration: 107.57 ms	Billed Duration: 108 ms	Memory Size: 256 MB	Max Memory Used: 106 MB	
```
