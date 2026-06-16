# Payments Lambda logs

- Function: `cif-portal-payments-dev`
- Window: last 15 minute(s)
- Filter: `(none)`
- Captured at: 2026-06-16T23:31:06Z

## 68 event(s)

```
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
23:18:08  START RequestId: 750966f5-31f0-46d5-ac73-f428e1820d8c Version: $LATEST
23:18:08  [payments] entry path='/dev/api/my-cards' method='POST'
23:18:08  [INFO]	2026-06-16T23:18:08.845Z	750966f5-31f0-46d5-ac73-f428e1820d8c	GetCustomerCardTypes loaded: {3: 'AMEX', 4: 'Discover', 7: 'Insight', 1: 'MasterCard', 9: 'Netspend DDA', 8: 'Netspend GPR', 2: 'Visa'}
23:18:08  [WARNING]	2026-06-16T23:18:08.984Z	750966f5-31f0-46d5-ac73-f428e1820d8c	Vergent POST https://api.repayonline.com/rgapi/v1.0/customers/601488/cardtokens -> 404: {
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
23:18:09  [WARNING]	2026-06-16T23:18:09.075Z	750966f5-31f0-46d5-ac73-f428e1820d8c	Vergent POST https://api.repayonline.com/rgapi/v1.0/customers -> 400: {
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
23:18:09  [INFO]	2026-06-16T23:18:09.075Z	750966f5-31f0-46d5-ac73-f428e1820d8c	repay create-customer cid=601488 status=400 body={
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
23:18:09  [WARNING]	2026-06-16T23:18:09.175Z	750966f5-31f0-46d5-ac73-f428e1820d8c	Vergent POST https://api.repayonline.com/rgapi/v1.0/customers/601488/cardtokens -> 404: {
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
23:18:09  [WARNING]	2026-06-16T23:18:09.175Z	750966f5-31f0-46d5-ac73-f428e1820d8c	repay cardtoken cid=601488 status=404 FULL={
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
23:18:09  [WARNING]	2026-06-16T23:18:09.175Z	750966f5-31f0-46d5-ac73-f428e1820d8c	save-card tokenize failed cid=601488 reason=repay_http_404
23:18:09  END RequestId: 750966f5-31f0-46d5-ac73-f428e1820d8c
23:18:09  REPORT RequestId: 750966f5-31f0-46d5-ac73-f428e1820d8c	Duration: 415.54 ms	Billed Duration: 416 ms	Memory Size: 256 MB	Max Memory Used: 106 MB	
23:18:13  START RequestId: 6c8280fb-7325-4155-be8a-8e063ba2e658 Version: $LATEST
23:18:13  [payments] entry path='/dev/api/my-cards' method='POST'
23:18:13  [WARNING]	2026-06-16T23:18:13.991Z	6c8280fb-7325-4155-be8a-8e063ba2e658	Vergent POST https://api.repayonline.com/rgapi/v1.0/customers/601488/cardtokens -> 404: {
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
23:18:14  [WARNING]	2026-06-16T23:18:14.082Z	6c8280fb-7325-4155-be8a-8e063ba2e658	Vergent POST https://api.repayonline.com/rgapi/v1.0/customers -> 400: {
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
23:18:14  [INFO]	2026-06-16T23:18:14.083Z	6c8280fb-7325-4155-be8a-8e063ba2e658	repay create-customer cid=601488 status=400 body={
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
23:18:14  [WARNING]	2026-06-16T23:18:14.191Z	6c8280fb-7325-4155-be8a-8e063ba2e658	Vergent POST https://api.repayonline.com/rgapi/v1.0/customers/601488/cardtokens -> 404: {
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
23:18:14  [WARNING]	2026-06-16T23:18:14.191Z	6c8280fb-7325-4155-be8a-8e063ba2e658	repay cardtoken cid=601488 status=404 FULL={
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
23:18:14  [WARNING]	2026-06-16T23:18:14.191Z	6c8280fb-7325-4155-be8a-8e063ba2e658	save-card tokenize failed cid=601488 reason=repay_http_404
23:18:14  END RequestId: 6c8280fb-7325-4155-be8a-8e063ba2e658
23:18:14  REPORT RequestId: 6c8280fb-7325-4155-be8a-8e063ba2e658	Duration: 330.92 ms	Billed Duration: 331 ms	Memory Size: 256 MB	Max Memory Used: 106 MB	
23:28:57  INIT_START Runtime Version: python:3.12.mainlinev2.v11	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:bec1042407ffdf4a1e2261cba8ed01949f62579da0d7ee83345b26dd8890eef8
23:28:57  INIT_START Runtime Version: python:3.12.mainlinev2.v11	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:bec1042407ffdf4a1e2261cba8ed01949f62579da0d7ee83345b26dd8890eef8
23:28:57  START RequestId: 0d9464d0-2559-404c-b345-5995da852f30 Version: $LATEST
23:28:57  [payments] entry path='/dev/api/my-payment/loan-summary' method='GET'
23:28:58  START RequestId: 09018110-5ff4-48e4-af7f-94d9feaa6ea1 Version: $LATEST
23:28:58  [payments] entry path='/dev/api/my-cards' method='GET'
23:28:58  [INFO]	2026-06-16T23:28:58.277Z	0d9464d0-2559-404c-b345-5995da852f30	v1 service Token cached (3600s) userId=8434
23:28:58  [INFO]	2026-06-16T23:28:58.473Z	09018110-5ff4-48e4-af7f-94d9feaa6ea1	v1 service Token cached (3600s) userId=8434
23:28:58  [INFO]	2026-06-16T23:28:58.562Z	09018110-5ff4-48e4-af7f-94d9feaa6ea1	GetCustomerCards cid=601488 count=5 cards=[{'id': 237669, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237131, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237130, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}, {'id': 237129, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 1}, {'id': 237127, 'type_id': 2, 'holder': 'Harut Darakchyan', 'last4': '', 'is_existing': False, 'is_active': False, 'CardProcessor': 'None', 'card_processor_type': 0}]
23:28:58  [INFO]	2026-06-16T23:28:58.615Z	09018110-5ff4-48e4-af7f-94d9feaa6ea1	GetCustomerCardTypes loaded: {3: 'AMEX', 4: 'Discover', 7: 'Insight', 1: 'MasterCard', 9: 'Netspend DDA', 8: 'Netspend GPR', 2: 'Visa'}
23:28:58  END RequestId: 09018110-5ff4-48e4-af7f-94d9feaa6ea1
23:28:58  REPORT RequestId: 09018110-5ff4-48e4-af7f-94d9feaa6ea1	Duration: 582.06 ms	Billed Duration: 1236 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	Init Duration: 653.63 ms	
23:29:01  END RequestId: 0d9464d0-2559-404c-b345-5995da852f30
23:29:01  REPORT RequestId: 0d9464d0-2559-404c-b345-5995da852f30	Duration: 3423.01 ms	Billed Duration: 3932 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	Init Duration: 508.22 ms	
23:29:29  START RequestId: 38768243-e36d-43d9-96d3-48cea142d515 Version: $LATEST
23:29:29  [payments] entry path='/dev/api/my-cards' method='POST'
23:29:29  [INFO]	2026-06-16T23:29:29.863Z	38768243-e36d-43d9-96d3-48cea142d515	GetCustomerCardTypes loaded: {3: 'AMEX', 4: 'Discover', 7: 'Insight', 1: 'MasterCard', 9: 'Netspend DDA', 8: 'Netspend GPR', 2: 'Visa'}
23:29:30  [WARNING]	2026-06-16T23:29:29.999Z	38768243-e36d-43d9-96d3-48cea142d515	Vergent POST https://api.repayonline.com/rgapi/v1.0/customers/601488/cardtokens -> 404: {
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
23:29:30  [INFO]	2026-06-16T23:29:30.123Z	38768243-e36d-43d9-96d3-48cea142d515	repay create-customer cid=601488 status=200 body={
  "customer_key": 1113400693,
  "merchant_key": 1073745651,
  "status": "Active",
  "customer_id": "",
  "customer_name": null,
  "contact": {
    "email": "",
    "first_name": "Harut",
    "last_name": "Darakchyan",
    "address": {
      "street": "",
      "street2": null,
      "city": "",
      "state": "",
      "zip": "",
      "country_code": ""
    }
  }
}
23:29:30  [WARNING]	2026-06-16T23:29:30.240Z	38768243-e36d-43d9-96d3-48cea142d515	Vergent POST https://api.repayonline.com/rgapi/v1.0/customers/601488/cardtokens -> 404: {
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
23:29:30  [WARNING]	2026-06-16T23:29:30.240Z	38768243-e36d-43d9-96d3-48cea142d515	repay cardtoken cid=601488 status=404 FULL={
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
23:29:30  [WARNING]	2026-06-16T23:29:30.240Z	38768243-e36d-43d9-96d3-48cea142d515	save-card tokenize failed cid=601488 reason=repay_http_404
23:29:30  END RequestId: 38768243-e36d-43d9-96d3-48cea142d515
23:29:30  REPORT RequestId: 38768243-e36d-43d9-96d3-48cea142d515	Duration: 501.54 ms	Billed Duration: 502 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	
23:29:33  START RequestId: cfab150f-7229-4ede-9a00-281e60f9ac3e Version: $LATEST
23:29:33  [payments] entry path='/dev/api/my-cards' method='POST'
23:29:33  [WARNING]	2026-06-16T23:29:33.785Z	cfab150f-7229-4ede-9a00-281e60f9ac3e	Vergent POST https://api.repayonline.com/rgapi/v1.0/customers/601488/cardtokens -> 404: {
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
23:29:33  [INFO]	2026-06-16T23:29:33.899Z	cfab150f-7229-4ede-9a00-281e60f9ac3e	repay create-customer cid=601488 status=200 body={
  "customer_key": 1113400695,
  "merchant_key": 1073745651,
  "status": "Active",
  "customer_id": "",
  "customer_name": null,
  "contact": {
    "email": "",
    "first_name": "Harut",
    "last_name": "Darakchyan",
    "address": {
      "street": "",
      "street2": null,
      "city": "",
      "state": "",
      "zip": "",
      "country_code": ""
    }
  }
}
23:29:34  [WARNING]	2026-06-16T23:29:34.013Z	cfab150f-7229-4ede-9a00-281e60f9ac3e	Vergent POST https://api.repayonline.com/rgapi/v1.0/customers/601488/cardtokens -> 404: {
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
23:29:34  [WARNING]	2026-06-16T23:29:34.013Z	cfab150f-7229-4ede-9a00-281e60f9ac3e	repay cardtoken cid=601488 status=404 FULL={
  "message": "Customer with key 601488 not found.",
  "status_code": 404,
  "validation_errors": null
}
23:29:34  [WARNING]	2026-06-16T23:29:34.013Z	cfab150f-7229-4ede-9a00-281e60f9ac3e	save-card tokenize failed cid=601488 reason=repay_http_404
23:29:34  END RequestId: cfab150f-7229-4ede-9a00-281e60f9ac3e
23:29:34  REPORT RequestId: cfab150f-7229-4ede-9a00-281e60f9ac3e	Duration: 336.08 ms	Billed Duration: 337 ms	Memory Size: 256 MB	Max Memory Used: 105 MB	
```
