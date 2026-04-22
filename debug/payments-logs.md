# Payments Lambda logs

- Function: `cif-portal-payments-dev`
- Window: last 30 minute(s)
- Filter: `(none)`
- Captured at: 2026-04-22T17:59:18Z

## 64 event(s)

```
17:35:26  INIT_START Runtime Version: python:3.12.mainlinev2.v7	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:2b830756c5b10ff133ebda3f21aaa7e31ccd9f7038e1342adb459865da7617a3
17:35:27  INIT_START Runtime Version: python:3.12.mainlinev2.v7	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:2b830756c5b10ff133ebda3f21aaa7e31ccd9f7038e1342adb459865da7617a3
17:35:27  [INFO]	2026-04-22T17:35:27.117Z		Found credentials in environment variables.
17:35:27  START RequestId: c2eff4ab-015b-4407-bf88-040c9264d447 Version: $LATEST
17:35:27  [INFO]	2026-04-22T17:35:27.404Z		Found credentials in environment variables.
17:35:27  START RequestId: 31adeae3-63a6-475d-a6ee-9a0aa6ca2a6b Version: $LATEST
17:35:27  [INFO]	2026-04-22T17:35:27.702Z	c2eff4ab-015b-4407-bf88-040c9264d447	v1 service Token cached (3600s) userId=8434
17:35:27  [INFO]	2026-04-22T17:35:27.938Z	31adeae3-63a6-475d-a6ee-9a0aa6ca2a6b	v1 service Token cached (3600s) userId=8434
17:35:28  END RequestId: 31adeae3-63a6-475d-a6ee-9a0aa6ca2a6b
17:35:28  REPORT RequestId: 31adeae3-63a6-475d-a6ee-9a0aa6ca2a6b	Duration: 520.22 ms	Billed Duration: 1015 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	Init Duration: 494.76 ms	
17:35:28  [INFO]	2026-04-22T17:35:28.306Z	c2eff4ab-015b-4407-bf88-040c9264d447	autopay probe hdr_id=4823221 hdr_keys=['AchOptOut', 'AmountDue', 'ChannelId', 'CompanyId', 'CosignerId', 'CustomerId', 'DueDate', 'Errors', 'FundingDate', 'HeldBankAccountId', 'HeldCheckNumber', 'InitialLoanStatus', 'IsEligibleForRefi', 'IsInRescindPeriod', 'IsStatusOutstanding', 'LoanAmount', 'LoanClassId', 'LoanModelId', 'LoanModelName', 'LoanTypeName', 'LocCreditLimit', 'MinAmountDue', 'MinLoanAmount', 'NumberOfPayments', 'OriginationDate', 'PaymentBankAccountId', 'PayoffAmount', 'PrinPerPayment', 'PrinReduction', 'RPP', 'RescindEndDate', 'RescindType', 'RescindValue', 'StatusId', 'StoreId', 'SubStatusId', 'ToCustomer', 'adv_trans_id', 'hdr_id', 'original_hdr_id', 'prev_hdr_id', 'prev_sys_id', 'product_root_hdr_id', 'root_hdr_id'] detail_keys=['AccountNum', 'AutoPayCardId', 'AutoPayMethod', 'AvailableCredit', 'Balance', 'CreditLimit', 'DaysLate', 'EarnedFees', 'EarnedPrin', 'Errors', 'FeeBalance', 'IRepoStatus', 'IsAutoPay', 'IsSoftVoid', 'LastPmtDate', 'Lender', 'LoanModelName', 'PaidOffDate', 'PastDueAmount', 'PrinBalance', 'PublicLoanId', 'Recent', 'StateDbId', 'Status', 'StoreName', 'SubStatus', 'SuretyBondCo', 'Tags']
17:35:28  END RequestId: c2eff4ab-015b-4407-bf88-040c9264d447
17:35:28  REPORT RequestId: c2eff4ab-015b-4407-bf88-040c9264d447	Duration: 980.52 ms	Billed Duration: 1527 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	Init Duration: 546.39 ms	
17:36:09  START RequestId: db23358a-885f-4fc6-9062-119c416e0888 Version: $LATEST
17:36:09  [INFO]	2026-04-22T17:36:09.217Z	db23358a-885f-4fc6-9062-119c416e0888	add card attempt cid=601488 last4=4242 brand=Visa exp=11/2028
17:36:09  [WARNING]	2026-04-22T17:36:09.328Z	db23358a-885f-4fc6-9062-119c416e0888	Vergent POST https://shared.vergentlms.com/api/api/V1/PostCustomerCard -> 400: {
  "id": 0,
  "company_id": 386,
  "customer_id": 601488,
  "card_type_id": 1,
  "card_holder": "Test Customer",
  "card_number": "4242424242424242",
  "card_id": "",
  "card_ref": "",
  "is_eligible_for_disbursement": false,
  "card_account_guid": null,
  "card_guid": null,
  "last_fou
17:36:09  [WARNING]	2026-04-22T17:36:09.329Z	db23358a-885f-4fc6-9062-119c416e0888	PostCustomerCard upstream status=400 raw={
  "id": 0,
  "company_id": 386,
  "customer_id": 601488,
  "card_type_id": 1,
  "card_holder": "Test Customer",
  "card_number": "4242424242424242",
  "card_id": "",
  "card_ref": "",
  "is_eligible_for_disbursement": false,
  "card_account_guid": null,
  "card_guid": null,
  "last_fou
17:36:09  END RequestId: db23358a-885f-4fc6-9062-119c416e0888
17:36:09  REPORT RequestId: db23358a-885f-4fc6-9062-119c416e0888	Duration: 114.37 ms	Billed Duration: 115 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	
17:38:16  START RequestId: cc093a93-b868-4b69-97bf-2d301a81a897 Version: $LATEST
17:38:16  START RequestId: 650cc019-6aa5-4c9b-85c1-daa2c7036f2a Version: $LATEST
17:38:16  END RequestId: 650cc019-6aa5-4c9b-85c1-daa2c7036f2a
17:38:16  REPORT RequestId: 650cc019-6aa5-4c9b-85c1-daa2c7036f2a	Duration: 90.59 ms	Billed Duration: 91 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	
17:38:17  [INFO]	2026-04-22T17:38:17.229Z	cc093a93-b868-4b69-97bf-2d301a81a897	autopay probe hdr_id=4823221 hdr_keys=['AchOptOut', 'AmountDue', 'ChannelId', 'CompanyId', 'CosignerId', 'CustomerId', 'DueDate', 'Errors', 'FundingDate', 'HeldBankAccountId', 'HeldCheckNumber', 'InitialLoanStatus', 'IsEligibleForRefi', 'IsInRescindPeriod', 'IsStatusOutstanding', 'LoanAmount', 'LoanClassId', 'LoanModelId', 'LoanModelName', 'LoanTypeName', 'LocCreditLimit', 'MinAmountDue', 'MinLoanAmount', 'NumberOfPayments', 'OriginationDate', 'PaymentBankAccountId', 'PayoffAmount', 'PrinPerPayment', 'PrinReduction', 'RPP', 'RescindEndDate', 'RescindType', 'RescindValue', 'StatusId', 'StoreId', 'SubStatusId', 'ToCustomer', 'adv_trans_id', 'hdr_id', 'original_hdr_id', 'prev_hdr_id', 'prev_sys_id', 'product_root_hdr_id', 'root_hdr_id'] detail_keys=['AccountNum', 'AutoPayCardId', 'AutoPayMethod', 'AvailableCredit', 'Balance', 'CreditLimit', 'DaysLate', 'EarnedFees', 'EarnedPrin', 'Errors', 'FeeBalance', 'IRepoStatus', 'IsAutoPay', 'IsSoftVoid', 'LastPmtDate', 'Lender', 'LoanModelName', 'PaidOffDate', 'PastDueAmount', 'PrinBalance', 'PublicLoanId', 'Recent', 'StateDbId', 'Status', 'StoreName', 'SubStatus', 'SuretyBondCo', 'Tags']
17:38:17  END RequestId: cc093a93-b868-4b69-97bf-2d301a81a897
17:38:17  REPORT RequestId: cc093a93-b868-4b69-97bf-2d301a81a897	Duration: 722.77 ms	Billed Duration: 723 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	
17:48:31  INIT_START Runtime Version: python:3.12.mainlinev2.v7	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:2b830756c5b10ff133ebda3f21aaa7e31ccd9f7038e1342adb459865da7617a3
17:48:31  [INFO]	2026-04-22T17:48:31.960Z		Found credentials in environment variables.
17:48:32  START RequestId: c81535f7-2510-4c0b-bd06-ba690329cf0a Version: $LATEST
17:48:32  [INFO]	2026-04-22T17:48:32.505Z	c81535f7-2510-4c0b-bd06-ba690329cf0a	v1 service Token cached (3600s) userId=8434
17:48:32  END RequestId: c81535f7-2510-4c0b-bd06-ba690329cf0a
17:48:32  REPORT RequestId: c81535f7-2510-4c0b-bd06-ba690329cf0a	Duration: 616.45 ms	Billed Duration: 981 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	Init Duration: 363.93 ms	
17:49:03  START RequestId: 89e8d1e4-93c5-4a9d-899f-61e906799b04 Version: $LATEST
17:49:03  END RequestId: 89e8d1e4-93c5-4a9d-899f-61e906799b04
17:49:03  REPORT RequestId: 89e8d1e4-93c5-4a9d-899f-61e906799b04	Duration: 74.83 ms	Billed Duration: 75 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	
17:49:03  START RequestId: 10ffd185-9b5f-45bb-aabb-ce6ce770e77d Version: $LATEST
17:49:03  END RequestId: 10ffd185-9b5f-45bb-aabb-ce6ce770e77d
17:49:03  REPORT RequestId: 10ffd185-9b5f-45bb-aabb-ce6ce770e77d	Duration: 74.75 ms	Billed Duration: 75 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	
17:54:05  INIT_START Runtime Version: python:3.12.mainlinev2.v7	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:2b830756c5b10ff133ebda3f21aaa7e31ccd9f7038e1342adb459865da7617a3
17:54:05  INIT_START Runtime Version: python:3.12.mainlinev2.v7	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:2b830756c5b10ff133ebda3f21aaa7e31ccd9f7038e1342adb459865da7617a3
17:54:05  INIT_START Runtime Version: python:3.12.mainlinev2.v7	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:2b830756c5b10ff133ebda3f21aaa7e31ccd9f7038e1342adb459865da7617a3
17:54:05  [INFO]	2026-04-22T17:54:05.798Z		Found credentials in environment variables.
17:54:05  [INFO]	2026-04-22T17:54:05.826Z		Found credentials in environment variables.
17:54:05  [INFO]	2026-04-22T17:54:05.842Z		Found credentials in environment variables.
17:54:05  START RequestId: d60f9bfd-5936-46cf-9c4d-46738e062a0d Version: $LATEST
17:54:05  START RequestId: d562fd5f-8ed5-4a87-b741-be7c14ffd273 Version: $LATEST
17:54:05  START RequestId: 07ec87bf-d479-46b9-a532-d1dcceaee4f9 Version: $LATEST
17:54:06  [INFO]	2026-04-22T17:54:06.377Z	d60f9bfd-5936-46cf-9c4d-46738e062a0d	v1 service Token cached (3600s) userId=8434
17:54:06  [INFO]	2026-04-22T17:54:06.395Z	d562fd5f-8ed5-4a87-b741-be7c14ffd273	v1 service Token cached (3600s) userId=8434
17:54:06  [INFO]	2026-04-22T17:54:06.405Z	07ec87bf-d479-46b9-a532-d1dcceaee4f9	v1 service Token cached (3600s) userId=8434
17:54:06  [INFO]	2026-04-22T17:54:06.449Z	d60f9bfd-5936-46cf-9c4d-46738e062a0d	GetCustomerBanks probe cid=601488 count=1 first_keys=['AccountNum', 'AccountOpenDate', 'BankVerification', 'CodChkNum', 'CompanyId', 'CustomerId', 'DDAPRN', 'Errors', 'IsDDA', 'IsDirectDep', 'IsPrimary', 'Name', 'Phone', 'PrevStmtDate', 'RoutingNum', 'Status', 'TypeId', 'TypeName', 'id']
17:54:06  END RequestId: d60f9bfd-5936-46cf-9c4d-46738e062a0d
17:54:06  REPORT RequestId: d60f9bfd-5936-46cf-9c4d-46738e062a0d	Duration: 512.23 ms	Billed Duration: 991 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	Init Duration: 478.52 ms	
17:54:06  END RequestId: d562fd5f-8ed5-4a87-b741-be7c14ffd273
17:54:06  REPORT RequestId: d562fd5f-8ed5-4a87-b741-be7c14ffd273	Duration: 524.27 ms	Billed Duration: 1004 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	Init Duration: 479.51 ms	
17:54:07  [INFO]	2026-04-22T17:54:07.126Z	07ec87bf-d479-46b9-a532-d1dcceaee4f9	autopay probe hdr_id=4823221 hdr_keys=['AchOptOut', 'AmountDue', 'ChannelId', 'CompanyId', 'CosignerId', 'CustomerId', 'DueDate', 'Errors', 'FundingDate', 'HeldBankAccountId', 'HeldCheckNumber', 'InitialLoanStatus', 'IsEligibleForRefi', 'IsInRescindPeriod', 'IsStatusOutstanding', 'LoanAmount', 'LoanClassId', 'LoanModelId', 'LoanModelName', 'LoanTypeName', 'LocCreditLimit', 'MinAmountDue', 'MinLoanAmount', 'NumberOfPayments', 'OriginationDate', 'PaymentBankAccountId', 'PayoffAmount', 'PrinPerPayment', 'PrinReduction', 'RPP', 'RescindEndDate', 'RescindType', 'RescindValue', 'StatusId', 'StoreId', 'SubStatusId', 'ToCustomer', 'adv_trans_id', 'hdr_id', 'original_hdr_id', 'prev_hdr_id', 'prev_sys_id', 'product_root_hdr_id', 'root_hdr_id'] detail_keys=['AccountNum', 'AutoPayCardId', 'AutoPayMethod', 'AvailableCredit', 'Balance', 'CreditLimit', 'DaysLate', 'EarnedFees', 'EarnedPrin', 'Errors', 'FeeBalance', 'IRepoStatus', 'IsAutoPay', 'IsSoftVoid', 'LastPmtDate', 'Lender', 'LoanModelName', 'PaidOffDate', 'PastDueAmount', 'PrinBalance', 'PublicLoanId', 'Recent', 'StateDbId', 'Status', 'StoreName', 'SubStatus', 'SuretyBondCo', 'Tags']
17:54:07  END RequestId: 07ec87bf-d479-46b9-a532-d1dcceaee4f9
17:54:07  REPORT RequestId: 07ec87bf-d479-46b9-a532-d1dcceaee4f9	Duration: 1144.55 ms	Billed Duration: 1665 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	Init Duration: 519.80 ms	
17:54:50  START RequestId: d0969e2c-da99-4762-aa89-e6401f21392a Version: $LATEST
17:54:50  [INFO]	2026-04-22T17:54:50.991Z	d0969e2c-da99-4762-aa89-e6401f21392a	add card attempt cid=601488 last4=0295 brand=Visa exp=04/2031
17:54:51  [WARNING]	2026-04-22T17:54:51.092Z	d0969e2c-da99-4762-aa89-e6401f21392a	Vergent POST https://shared.vergentlms.com/api/api/V1/PostCustomerCard -> 400: {
  "id": 0,
  "company_id": 386,
  "customer_id": 601488,
  "card_type_id": 1,
  "card_holder": "Harut Darakchyan",
  "card_number": "4833160326650295",
  "card_id": "",
  "card_ref": "",
  "is_eligible_for_disbursement": false,
  "card_account_guid": null,
  "card_guid": null,
  "last_
17:54:51  [WARNING]	2026-04-22T17:54:51.093Z	d0969e2c-da99-4762-aa89-e6401f21392a	PostCustomerCard upstream status=400 raw={
  "id": 0,
  "company_id": 386,
  "customer_id": 601488,
  "card_type_id": 1,
  "card_holder": "Harut Darakchyan",
  "card_number": "4833160326650295",
  "card_id": "",
  "card_ref": "",
  "is_eligible_for_disbursement": false,
  "card_account_guid": null,
  "card_guid": null,
  "last_
17:54:51  END RequestId: d0969e2c-da99-4762-aa89-e6401f21392a
17:54:51  REPORT RequestId: d0969e2c-da99-4762-aa89-e6401f21392a	Duration: 103.85 ms	Billed Duration: 104 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	
```
