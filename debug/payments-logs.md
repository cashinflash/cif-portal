# Payments Lambda logs

- Function: `cif-portal-payments-dev`
- Window: last 90 minute(s)
- Filter: `(none)`
- Captured at: 2026-06-16T23:18:03Z

## 76 event(s)

```
21:56:21  INIT_START Runtime Version: python:3.12.mainlinev2.v11	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:bec1042407ffdf4a1e2261cba8ed01949f62579da0d7ee83345b26dd8890eef8
21:56:21  INIT_START Runtime Version: python:3.12.mainlinev2.v11	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:bec1042407ffdf4a1e2261cba8ed01949f62579da0d7ee83345b26dd8890eef8
21:56:22  START RequestId: 90667dfa-1ecc-43a8-b3c5-ce4608d6da39 Version: $LATEST
21:56:22  [payments] entry path='/dev/api/my-cards' method='GET'
21:56:22  START RequestId: af0d1ff6-729c-4a06-8556-a6802de46063 Version: $LATEST
21:56:22  [payments] entry path='/dev/api/my-payment/loan-summary' method='GET'
21:56:22  [INFO]	2026-06-16T21:56:22.515Z	af0d1ff6-729c-4a06-8556-a6802de46063	v1 service Token cached (3600s) userId=8434
21:56:22  [INFO]	2026-06-16T21:56:22.548Z	90667dfa-1ecc-43a8-b3c5-ce4608d6da39	v1 service Token cached (3600s) userId=8434
21:56:22  [INFO]	2026-06-16T21:56:22.647Z	90667dfa-1ecc-43a8-b3c5-ce4608d6da39	GetCustomerCards cid=601488 count=5 cards=[{'id': 237669, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237131, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237130, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237129, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 1}, {'id': 237127, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}]
21:56:22  [INFO]	2026-06-16T21:56:22.719Z	90667dfa-1ecc-43a8-b3c5-ce4608d6da39	GetCustomerCardTypes loaded: {3: 'AMEX', 4: 'Discover', 7: 'Insight', 1: 'MasterCard', 9: 'Netspend DDA', 8: 'Netspend GPR', 2: 'Visa'}
21:56:22  END RequestId: 90667dfa-1ecc-43a8-b3c5-ce4608d6da39
21:56:22  REPORT RequestId: 90667dfa-1ecc-43a8-b3c5-ce4608d6da39	Duration: 694.43 ms	Billed Duration: 1341 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	Init Duration: 646.46 ms	
21:56:25  END RequestId: af0d1ff6-729c-4a06-8556-a6802de46063
21:56:25  REPORT RequestId: af0d1ff6-729c-4a06-8556-a6802de46063	Duration: 3431.50 ms	Billed Duration: 4118 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	Init Duration: 685.92 ms	
21:56:41  START RequestId: 95a608c5-c42b-4b29-8e83-048c07fa6750 Version: $LATEST
21:56:41  [payments] entry path='/dev/api/my-cards' method='POST'
21:56:41  [INFO]	2026-06-16T21:56:41.311Z	95a608c5-c42b-4b29-8e83-048c07fa6750	GetCustomerCardTypes loaded: {3: 'AMEX', 4: 'Discover', 7: 'Insight', 1: 'MasterCard', 9: 'Netspend DDA', 8: 'Netspend GPR', 2: 'Visa'}
21:56:42  [WARNING]	2026-06-16T21:56:42.385Z	95a608c5-c42b-4b29-8e83-048c07fa6750	cardsafe StoreCard cid=601488 NO-TOKEN-FULL=<?xml version="1.0" encoding="utf-8"?> <Response xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="https://api.repayonline.com/ws/">   <Result>1001</Result>   <RespMSG>Invalid Account Status</RespMSG>   <AuthCode /> </Response>
21:56:42  [WARNING]	2026-06-16T21:56:42.386Z	95a608c5-c42b-4b29-8e83-048c07fa6750	save-card tokenize failed cid=601488 reason=cardsafe_no_token
21:56:42  END RequestId: 95a608c5-c42b-4b29-8e83-048c07fa6750
21:56:42  REPORT RequestId: 95a608c5-c42b-4b29-8e83-048c07fa6750	Duration: 1190.54 ms	Billed Duration: 1191 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	
21:56:52  START RequestId: 612e35e4-dde8-4e98-81c5-2c15daf30be6 Version: $LATEST
21:56:52  [payments] entry path='/dev/api/my-cards' method='POST'
21:56:53  [WARNING]	2026-06-16T21:56:53.625Z	612e35e4-dde8-4e98-81c5-2c15daf30be6	cardsafe StoreCard cid=601488 NO-TOKEN-FULL=<?xml version="1.0" encoding="utf-8"?> <Response xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="https://api.repayonline.com/ws/">   <Result>1001</Result>   <RespMSG>Invalid Account Status</RespMSG>   <AuthCode /> </Response>
21:56:53  [WARNING]	2026-06-16T21:56:53.625Z	612e35e4-dde8-4e98-81c5-2c15daf30be6	save-card tokenize failed cid=601488 reason=cardsafe_no_token
21:56:53  END RequestId: 612e35e4-dde8-4e98-81c5-2c15daf30be6
21:56:53  REPORT RequestId: 612e35e4-dde8-4e98-81c5-2c15daf30be6	Duration: 939.74 ms	Billed Duration: 940 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	
22:37:58  INIT_START Runtime Version: python:3.12.mainlinev2.v11	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:bec1042407ffdf4a1e2261cba8ed01949f62579da0d7ee83345b26dd8890eef8
22:37:58  INIT_START Runtime Version: python:3.12.mainlinev2.v11	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:bec1042407ffdf4a1e2261cba8ed01949f62579da0d7ee83345b26dd8890eef8
22:37:59  START RequestId: 97b206be-f564-4e44-ae4e-14f63a643c4b Version: $LATEST
22:37:59  [payments] entry path='/dev/api/my-cards' method='GET'
22:37:59  START RequestId: eadc25cf-7e9b-4943-8c3e-01f3466df0a3 Version: $LATEST
22:37:59  [payments] entry path='/dev/api/my-payment/loan-summary' method='GET'
22:37:59  [INFO]	2026-06-16T22:37:59.557Z	97b206be-f564-4e44-ae4e-14f63a643c4b	v1 service Token cached (3600s) userId=8434
22:37:59  [INFO]	2026-06-16T22:37:59.655Z	97b206be-f564-4e44-ae4e-14f63a643c4b	GetCustomerCards cid=601488 count=5 cards=[{'id': 237669, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237131, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237130, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237129, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 1}, {'id': 237127, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}]
22:37:59  [INFO]	2026-06-16T22:37:59.730Z	eadc25cf-7e9b-4943-8c3e-01f3466df0a3	v1 service Token cached (3600s) userId=8434
22:37:59  [INFO]	2026-06-16T22:37:59.751Z	97b206be-f564-4e44-ae4e-14f63a643c4b	GetCustomerCardTypes loaded: {3: 'AMEX', 4: 'Discover', 7: 'Insight', 1: 'MasterCard', 9: 'Netspend DDA', 8: 'Netspend GPR', 2: 'Visa'}
22:37:59  END RequestId: 97b206be-f564-4e44-ae4e-14f63a643c4b
22:37:59  REPORT RequestId: 97b206be-f564-4e44-ae4e-14f63a643c4b	Duration: 598.52 ms	Billed Duration: 1111 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	Init Duration: 511.67 ms	
22:38:03  END RequestId: eadc25cf-7e9b-4943-8c3e-01f3466df0a3
22:38:03  REPORT RequestId: eadc25cf-7e9b-4943-8c3e-01f3466df0a3	Duration: 4451.13 ms	Billed Duration: 5077 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	Init Duration: 625.69 ms	
22:38:17  START RequestId: 96f020bd-6f31-4dfc-902e-7aee067d827d Version: $LATEST
22:38:17  [payments] entry path='/dev/api/my-cards' method='POST'
22:38:18  [INFO]	2026-06-16T22:38:18.054Z	96f020bd-6f31-4dfc-902e-7aee067d827d	GetCustomerCardTypes loaded: {3: 'AMEX', 4: 'Discover', 7: 'Insight', 1: 'MasterCard', 9: 'Netspend DDA', 8: 'Netspend GPR', 2: 'Visa'}
22:38:18  [WARNING]	2026-06-16T22:38:18.189Z	96f020bd-6f31-4dfc-902e-7aee067d827d	Vergent POST https://api.repayonline.com/rgapi/v1.0/customers/601488/cardtokens -> 404: {
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
22:38:18  [WARNING]	2026-06-16T22:38:18.279Z	96f020bd-6f31-4dfc-902e-7aee067d827d	Vergent POST https://api.repayonline.com/rgapi/v1.0/customers -> 400: {
  "message": "The contact field is required.",
  "status_code": 400,
  "validation_errors": [
    {
      "property": "request.contact",
      "message": "The contact field is required.",
      "custom_field": false,
      "error_code": null
    }
  ]
}
22:38:18  [INFO]	2026-06-16T22:38:18.279Z	96f020bd-6f31-4dfc-902e-7aee067d827d	repay create-customer cid=601488 status=400 body={
  "message": "The contact field is required.",
  "status_code": 400,
  "validation_errors": [
    {
      "property": "request.contact",
      "message": "The contact field is required.",
      "custom_field": false,
      "error_code": null
    }
  ]
}
22:38:18  [WARNING]	2026-06-16T22:38:18.382Z	96f020bd-6f31-4dfc-902e-7aee067d827d	Vergent POST https://api.repayonline.com/rgapi/v1.0/customers/601488/cardtokens -> 404: {
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
22:38:18  [WARNING]	2026-06-16T22:38:18.382Z	96f020bd-6f31-4dfc-902e-7aee067d827d	repay cardtoken cid=601488 status=404 FULL={
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
22:38:18  [WARNING]	2026-06-16T22:38:18.382Z	96f020bd-6f31-4dfc-902e-7aee067d827d	save-card tokenize failed cid=601488 reason=repay_http_404
22:38:18  END RequestId: 96f020bd-6f31-4dfc-902e-7aee067d827d
22:38:18  REPORT RequestId: 96f020bd-6f31-4dfc-902e-7aee067d827d	Duration: 400.62 ms	Billed Duration: 401 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	
22:38:20  START RequestId: 5c10a28e-0565-4178-9289-c6e046491e11 Version: $LATEST
22:38:20  [payments] entry path='/dev/api/my-cards' method='POST'
22:38:21  [WARNING]	2026-06-16T22:38:21.038Z	5c10a28e-0565-4178-9289-c6e046491e11	Vergent POST https://api.repayonline.com/rgapi/v1.0/customers/601488/cardtokens -> 404: {
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
22:38:21  [WARNING]	2026-06-16T22:38:21.126Z	5c10a28e-0565-4178-9289-c6e046491e11	Vergent POST https://api.repayonline.com/rgapi/v1.0/customers -> 400: {
  "message": "The contact field is required.",
  "status_code": 400,
  "validation_errors": [
    {
      "property": "request.contact",
      "message": "The contact field is required.",
      "custom_field": false,
      "error_code": null
    }
  ]
}
22:38:21  [INFO]	2026-06-16T22:38:21.126Z	5c10a28e-0565-4178-9289-c6e046491e11	repay create-customer cid=601488 status=400 body={
  "message": "The contact field is required.",
  "status_code": 400,
  "validation_errors": [
    {
      "property": "request.contact",
      "message": "The contact field is required.",
      "custom_field": false,
      "error_code": null
    }
  ]
}
22:38:21  [WARNING]	2026-06-16T22:38:21.241Z	5c10a28e-0565-4178-9289-c6e046491e11	Vergent POST https://api.repayonline.com/rgapi/v1.0/customers/601488/cardtokens -> 404: {
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
22:38:21  [WARNING]	2026-06-16T22:38:21.241Z	5c10a28e-0565-4178-9289-c6e046491e11	repay cardtoken cid=601488 status=404 FULL={
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
22:38:21  [WARNING]	2026-06-16T22:38:21.241Z	5c10a28e-0565-4178-9289-c6e046491e11	save-card tokenize failed cid=601488 reason=repay_http_404
22:38:21  END RequestId: 5c10a28e-0565-4178-9289-c6e046491e11
22:38:21  REPORT RequestId: 5c10a28e-0565-4178-9289-c6e046491e11	Duration: 305.70 ms	Billed Duration: 306 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	
23:17:00  INIT_START Runtime Version: python:3.12.mainlinev2.v11	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:bec1042407ffdf4a1e2261cba8ed01949f62579da0d7ee83345b26dd8890eef8
23:17:00  INIT_START Runtime Version: python:3.12.mainlinev2.v11	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:bec1042407ffdf4a1e2261cba8ed01949f62579da0d7ee83345b26dd8890eef8
23:17:00  START RequestId: 02b76085-ae40-4b21-83ea-88ee87ebf876 Version: $LATEST
23:17:00  [payments] entry path='/dev/api/my-cards' method='GET'
23:17:01  START RequestId: 229edb5d-f746-4ee2-8fe1-06b8ca3ba146 Version: $LATEST
23:17:01  [payments] entry path='/dev/api/my-payment/loan-summary' method='GET'
23:17:01  [INFO]	2026-06-16T23:17:01.185Z	02b76085-ae40-4b21-83ea-88ee87ebf876	v1 service Token cached (3600s) userId=8434
23:17:01  [INFO]	2026-06-16T23:17:01.299Z	02b76085-ae40-4b21-83ea-88ee87ebf876	GetCustomerCards cid=601488 count=5 cards=[{'id': 237669, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237131, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237130, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237129, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 1}, {'id': 237127, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}]
23:17:01  [INFO]	2026-06-16T23:17:01.358Z	02b76085-ae40-4b21-83ea-88ee87ebf876	GetCustomerCardTypes loaded: {3: 'AMEX', 4: 'Discover', 7: 'Insight', 1: 'MasterCard', 9: 'Netspend DDA', 8: 'Netspend GPR', 2: 'Visa'}
23:17:01  END RequestId: 02b76085-ae40-4b21-83ea-88ee87ebf876
23:17:01  REPORT RequestId: 02b76085-ae40-4b21-83ea-88ee87ebf876	Duration: 581.40 ms	Billed Duration: 1042 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	Init Duration: 459.98 ms	
23:17:01  [INFO]	2026-06-16T23:17:01.484Z	229edb5d-f746-4ee2-8fe1-06b8ca3ba146	v1 service Token cached (3600s) userId=8434
23:17:04  END RequestId: 229edb5d-f746-4ee2-8fe1-06b8ca3ba146
23:17:04  REPORT RequestId: 229edb5d-f746-4ee2-8fe1-06b8ca3ba146	Duration: 3662.62 ms	Billed Duration: 4337 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	Init Duration: 674.32 ms	
```
