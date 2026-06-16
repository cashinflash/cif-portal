# Payments Lambda logs

- Function: `cif-portal-payments-dev`
- Window: last 10 minute(s)
- Filter: `(none)`
- Captured at: 2026-06-16T21:58:29Z

## 27 event(s)

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
```
