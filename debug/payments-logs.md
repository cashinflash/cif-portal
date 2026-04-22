# Payments Lambda logs

- Function: `cif-portal-payments-dev`
- Window: last 30 minute(s)
- Filter: `(none)`
- Captured at: 2026-04-22T18:06:30Z

## 102 event(s)

```
17:38:16  START RequestId: cc093a93-b868-4b69-97bf-2d301a81a897 Version: $LATEST
17:38:16  START RequestId: 650cc019-6aa5-4c9b-85c1-daa2c7036f2a Version: $LATEST
17:38:16  END RequestId: 650cc019-6aa5-4c9b-85c1-daa2c7036f2a
17:38:16  REPORT RequestId: 650cc019-6aa5-4c9b-85c1-daa2c7036f2a	Duration: 90.59 ms	Billed Duration: 91 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	
17:38:17  [INFO]	2026-04-22T17:38:17.229Z	cc093a93-b868-4b69-97bf-2d301a81a897	autopay probe hdr_id=4823221 hdr_keys=['AchOptOut', 'AmountDue', 'ChannelId', 'CompanyId', 'CosignerId', 'CustomerId', 'DueDate', 'Errors', 'FundingDate', 'HeldBankAccountId', 'HeldCheckNumber', 'InitialLoanStatus', 'IsEligibleForRefi', 'IsInRescindPeriod', 'IsStatusOutstanding', 'LoanAmount', 'LoanClassId', 'LoanModelId', 'LoanModelName', 'LoanTypeName', 'LocCreditLimit', 'MinAmountDue', 'MinLoanAmount', 'NumberOfPayments', 'OriginationDate', 'PaymentBankAccountId', 'PayoffAmount', 'PrinPerPayment', 'PrinReduction', 'RPP', 'RescindEndDate', 'RescindType', 'RescindValue', 'StatusId', 'StoreId', 'SubStatusId', 'ToCustomer', 'adv_trans_id', 'hdr_id', 'original_hdr_id', 'prev_hdr_id', 'prev_sys_id', 'product_root_hdr_id', 'root_hdr_id'] detail_keys=['AccountNum', 'AutoPayCardId', 'AutoPayMethod', 'AvailableCredit', 'Balance', 'CreditLimit', 'DaysLate', 'EarnedFees', 'EarnedPrin', 'Errors', 'FeeBalance', 'IRepoStatus', 'IsAutoPay', 'IsSoftVoid', 'LastPmtDate', 'Lender', 'LoanModelName', 'PaidOffDate', 'PastDueAmount', 'PrinBalance', 'PublicLoanId', 'Recent', 'StateDbId', 'Status', 'StoreName', 'SubStatus', 'SuretyBondCo', 'Tags']
17:38:17  END RequestId: cc093a93-b868-4b69-97bf-2d301a81a897
17:38:17  REPORT RequestId: cc093a93-b868-4b69-97bf-2d301a81a897	Duration: 722.77 ms	Billed Duration: 723 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	
17:48:31  INIT_START Runtime Version: python:3.12.mainlinev2.v7	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:2b830756c5b10ff133ebda3f21aaa7e31ccd9f7038e1342adb459865da7617a3
17:48:31  INIT_START Runtime Version: python:3.12.mainlinev2.v7	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:2b830756c5b10ff133ebda3f21aaa7e31ccd9f7038e1342adb459865da7617a3
17:48:31  INIT_START Runtime Version: python:3.12.mainlinev2.v7	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:2b830756c5b10ff133ebda3f21aaa7e31ccd9f7038e1342adb459865da7617a3
17:48:31  [INFO]	2026-04-22T17:48:31.960Z		Found credentials in environment variables.
17:48:31  [INFO]	2026-04-22T17:48:31.962Z		Found credentials in environment variables.
17:48:32  [INFO]	2026-04-22T17:48:32.043Z		Found credentials in environment variables.
17:48:32  START RequestId: c81535f7-2510-4c0b-bd06-ba690329cf0a Version: $LATEST
17:48:32  START RequestId: 9ddf82d5-601d-41d7-a39d-6f89c7dfabad Version: $LATEST
17:48:32  START RequestId: d1bcb65d-600f-4086-b990-cbf9f7e80016 Version: $LATEST
17:48:32  [INFO]	2026-04-22T17:48:32.505Z	c81535f7-2510-4c0b-bd06-ba690329cf0a	v1 service Token cached (3600s) userId=8434
17:48:32  [INFO]	2026-04-22T17:48:32.525Z	9ddf82d5-601d-41d7-a39d-6f89c7dfabad	v1 service Token cached (3600s) userId=8434
17:48:32  [INFO]	2026-04-22T17:48:32.635Z	d1bcb65d-600f-4086-b990-cbf9f7e80016	v1 service Token cached (3600s) userId=8434
17:48:32  END RequestId: c81535f7-2510-4c0b-bd06-ba690329cf0a
17:48:32  REPORT RequestId: c81535f7-2510-4c0b-bd06-ba690329cf0a	Duration: 616.45 ms	Billed Duration: 981 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	Init Duration: 363.93 ms	
17:48:32  END RequestId: d1bcb65d-600f-4086-b990-cbf9f7e80016
17:48:32  REPORT RequestId: d1bcb65d-600f-4086-b990-cbf9f7e80016	Duration: 555.77 ms	Billed Duration: 1028 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	Init Duration: 472.13 ms	
17:48:33  [INFO]	2026-04-22T17:48:33.223Z	9ddf82d5-601d-41d7-a39d-6f89c7dfabad	autopay probe hdr_id=4823221 hdr_keys=['AchOptOut', 'AmountDue', 'ChannelId', 'CompanyId', 'CosignerId', 'CustomerId', 'DueDate', 'Errors', 'FundingDate', 'HeldBankAccountId', 'HeldCheckNumber', 'InitialLoanStatus', 'IsEligibleForRefi', 'IsInRescindPeriod', 'IsStatusOutstanding', 'LoanAmount', 'LoanClassId', 'LoanModelId', 'LoanModelName', 'LoanTypeName', 'LocCreditLimit', 'MinAmountDue', 'MinLoanAmount', 'NumberOfPayments', 'OriginationDate', 'PaymentBankAccountId', 'PayoffAmount', 'PrinPerPayment', 'PrinReduction', 'RPP', 'RescindEndDate', 'RescindType', 'RescindValue', 'StatusId', 'StoreId', 'SubStatusId', 'ToCustomer', 'adv_trans_id', 'hdr_id', 'original_hdr_id', 'prev_hdr_id', 'prev_sys_id', 'product_root_hdr_id', 'root_hdr_id'] detail_keys=['AccountNum', 'AutoPayCardId', 'AutoPayMethod', 'AvailableCredit', 'Balance', 'CreditLimit', 'DaysLate', 'EarnedFees', 'EarnedPrin', 'Errors', 'FeeBalance', 'IRepoStatus', 'IsAutoPay', 'IsSoftVoid', 'LastPmtDate', 'Lender', 'LoanModelName', 'PaidOffDate', 'PastDueAmount', 'PrinBalance', 'PublicLoanId', 'Recent', 'StateDbId', 'Status', 'StoreName', 'SubStatus', 'SuretyBondCo', 'Tags']
17:48:33  END RequestId: 9ddf82d5-601d-41d7-a39d-6f89c7dfabad
17:48:33  REPORT RequestId: 9ddf82d5-601d-41d7-a39d-6f89c7dfabad	Duration: 1160.86 ms	Billed Duration: 1535 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	Init Duration: 373.71 ms	
17:49:03  START RequestId: 89e8d1e4-93c5-4a9d-899f-61e906799b04 Version: $LATEST
17:49:03  START RequestId: 446bce07-4d70-4298-9bc5-f384bb587521 Version: $LATEST
17:49:03  END RequestId: 89e8d1e4-93c5-4a9d-899f-61e906799b04
17:49:03  REPORT RequestId: 89e8d1e4-93c5-4a9d-899f-61e906799b04	Duration: 74.83 ms	Billed Duration: 75 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	
17:49:03  START RequestId: 10ffd185-9b5f-45bb-aabb-ce6ce770e77d Version: $LATEST
17:49:03  END RequestId: 10ffd185-9b5f-45bb-aabb-ce6ce770e77d
17:49:03  REPORT RequestId: 10ffd185-9b5f-45bb-aabb-ce6ce770e77d	Duration: 74.75 ms	Billed Duration: 75 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	
17:49:04  [INFO]	2026-04-22T17:49:04.394Z	446bce07-4d70-4298-9bc5-f384bb587521	autopay probe hdr_id=4823221 hdr_keys=['AchOptOut', 'AmountDue', 'ChannelId', 'CompanyId', 'CosignerId', 'CustomerId', 'DueDate', 'Errors', 'FundingDate', 'HeldBankAccountId', 'HeldCheckNumber', 'InitialLoanStatus', 'IsEligibleForRefi', 'IsInRescindPeriod', 'IsStatusOutstanding', 'LoanAmount', 'LoanClassId', 'LoanModelId', 'LoanModelName', 'LoanTypeName', 'LocCreditLimit', 'MinAmountDue', 'MinLoanAmount', 'NumberOfPayments', 'OriginationDate', 'PaymentBankAccountId', 'PayoffAmount', 'PrinPerPayment', 'PrinReduction', 'RPP', 'RescindEndDate', 'RescindType', 'RescindValue', 'StatusId', 'StoreId', 'SubStatusId', 'ToCustomer', 'adv_trans_id', 'hdr_id', 'original_hdr_id', 'prev_hdr_id', 'prev_sys_id', 'product_root_hdr_id', 'root_hdr_id'] detail_keys=['AccountNum', 'AutoPayCardId', 'AutoPayMethod', 'AvailableCredit', 'Balance', 'CreditLimit', 'DaysLate', 'EarnedFees', 'EarnedPrin', 'Errors', 'FeeBalance', 'IRepoStatus', 'IsAutoPay', 'IsSoftVoid', 'LastPmtDate', 'Lender', 'LoanModelName', 'PaidOffDate', 'PastDueAmount', 'PrinBalance', 'PublicLoanId', 'Recent', 'StateDbId', 'Status', 'StoreName', 'SubStatus', 'SuretyBondCo', 'Tags']
17:49:04  END RequestId: 446bce07-4d70-4298-9bc5-f384bb587521
17:49:04  REPORT RequestId: 446bce07-4d70-4298-9bc5-f384bb587521	Duration: 668.12 ms	Billed Duration: 669 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	
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
18:02:32  INIT_START Runtime Version: python:3.12.mainlinev2.v7	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:2b830756c5b10ff133ebda3f21aaa7e31ccd9f7038e1342adb459865da7617a3
18:02:32  [INFO]	2026-04-22T18:02:32.588Z		Found credentials in environment variables.
18:05:29  INIT_START Runtime Version: python:3.12.mainlinev2.v7	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:2b830756c5b10ff133ebda3f21aaa7e31ccd9f7038e1342adb459865da7617a3
18:05:29  INIT_START Runtime Version: python:3.12.mainlinev2.v7	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:2b830756c5b10ff133ebda3f21aaa7e31ccd9f7038e1342adb459865da7617a3
18:05:29  INIT_START Runtime Version: python:3.12.mainlinev2.v7	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:2b830756c5b10ff133ebda3f21aaa7e31ccd9f7038e1342adb459865da7617a3
18:05:29  [INFO]	2026-04-22T18:05:29.591Z		Found credentials in environment variables.
18:05:29  [INFO]	2026-04-22T18:05:29.625Z		Found credentials in environment variables.
18:05:29  START RequestId: 4a690518-e92a-4eab-8122-02727e9fbfa2 Version: $LATEST
18:05:29  START RequestId: c902510b-0253-44b4-b4ac-ba1db3463cdb Version: $LATEST
18:05:29  [INFO]	2026-04-22T18:05:29.764Z		Found credentials in environment variables.
18:05:29  START RequestId: 0a7c731f-7ea3-4791-aaa8-641d95b9cfe2 Version: $LATEST
18:05:30  [INFO]	2026-04-22T18:05:30.058Z	c902510b-0253-44b4-b4ac-ba1db3463cdb	v1 service Token cached (3600s) userId=8434
18:05:30  [INFO]	2026-04-22T18:05:30.092Z	4a690518-e92a-4eab-8122-02727e9fbfa2	v1 service Token cached (3600s) userId=8434
18:05:30  [INFO]	2026-04-22T18:05:30.146Z	c902510b-0253-44b4-b4ac-ba1db3463cdb	GetCustomerBanks probe cid=601488 count=1 first_keys=['AccountNum', 'AccountOpenDate', 'BankVerification', 'CodChkNum', 'CompanyId', 'CustomerId', 'DDAPRN', 'Errors', 'IsDDA', 'IsDirectDep', 'IsPrimary', 'Name', 'Phone', 'PrevStmtDate', 'RoutingNum', 'Status', 'TypeId', 'TypeName', 'id']
18:05:30  END RequestId: c902510b-0253-44b4-b4ac-ba1db3463cdb
18:05:30  REPORT RequestId: c902510b-0253-44b4-b4ac-ba1db3463cdb	Duration: 424.22 ms	Billed Duration: 773 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	Init Duration: 348.32 ms	
18:05:30  [INFO]	2026-04-22T18:05:30.264Z	0a7c731f-7ea3-4791-aaa8-641d95b9cfe2	v1 service Token cached (3600s) userId=8434
18:05:30  END RequestId: 0a7c731f-7ea3-4791-aaa8-641d95b9cfe2
18:05:30  REPORT RequestId: 0a7c731f-7ea3-4791-aaa8-641d95b9cfe2	Duration: 458.11 ms	Billed Duration: 919 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	Init Duration: 460.30 ms	
18:05:30  [INFO]	2026-04-22T18:05:30.735Z	4a690518-e92a-4eab-8122-02727e9fbfa2	autopay probe hdr_id=4823221 hdr_keys=['AchOptOut', 'AmountDue', 'ChannelId', 'CompanyId', 'CosignerId', 'CustomerId', 'DueDate', 'Errors', 'FundingDate', 'HeldBankAccountId', 'HeldCheckNumber', 'InitialLoanStatus', 'IsEligibleForRefi', 'IsInRescindPeriod', 'IsStatusOutstanding', 'LoanAmount', 'LoanClassId', 'LoanModelId', 'LoanModelName', 'LoanTypeName', 'LocCreditLimit', 'MinAmountDue', 'MinLoanAmount', 'NumberOfPayments', 'OriginationDate', 'PaymentBankAccountId', 'PayoffAmount', 'PrinPerPayment', 'PrinReduction', 'RPP', 'RescindEndDate', 'RescindType', 'RescindValue', 'StatusId', 'StoreId', 'SubStatusId', 'ToCustomer', 'adv_trans_id', 'hdr_id', 'original_hdr_id', 'prev_hdr_id', 'prev_sys_id', 'product_root_hdr_id', 'root_hdr_id'] detail_keys=['AccountNum', 'AutoPayCardId', 'AutoPayMethod', 'AvailableCredit', 'Balance', 'CreditLimit', 'DaysLate', 'EarnedFees', 'EarnedPrin', 'Errors', 'FeeBalance', 'IRepoStatus', 'IsAutoPay', 'IsSoftVoid', 'LastPmtDate', 'Lender', 'LoanModelName', 'PaidOffDate', 'PastDueAmount', 'PrinBalance', 'PublicLoanId', 'Recent', 'StateDbId', 'Status', 'StoreName', 'SubStatus', 'SuretyBondCo', 'Tags']
18:05:30  END RequestId: 4a690518-e92a-4eab-8122-02727e9fbfa2
18:05:30  REPORT RequestId: 4a690518-e92a-4eab-8122-02727e9fbfa2	Duration: 1032.96 ms	Billed Duration: 1419 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	Init Duration: 385.90 ms	
18:05:45  START RequestId: 1f60973f-5546-4269-a285-b77d4bb49764 Version: $LATEST
18:05:45  [INFO]	2026-04-22T18:05:45.043Z	1f60973f-5546-4269-a285-b77d4bb49764	add card attempt cid=601488 last4=0295 brand=Visa exp=04/2031
18:05:45  [WARNING]	2026-04-22T18:05:45.159Z	1f60973f-5546-4269-a285-b77d4bb49764	Vergent POST https://shared.vergentlms.com/api/api/V1/PostCustomerCard -> 400: {
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
18:05:45  [WARNING]	2026-04-22T18:05:45.160Z	1f60973f-5546-4269-a285-b77d4bb49764	PostCustomerCard upstream status=400 body={'id': 0, 'company_id': 386, 'customer_id': 601488, 'card_type_id': 1, 'card_holder': 'Harut Darakchyan', 'card_number': '****0295', 'card_id': '', 'card_ref': '', 'is_eligible_for_disbursement': False, 'expire_month': 4, 'expire_year': 2031, 'ccv': '***'} raw={    "id": 0,    "company_id": 386,    "customer_id": 601488,    "card_type_id": 1,    "card_holder": "Harut Darakchyan",    "card_number": "4833160326650295",    "card_id": "",    "card_ref": "",    "is_eligible_for_disbursement": false,    "card_account_guid": null,    "card_guid": null,    "last_four_digits": null,    "product_id": 0,    "expire_month": 4,    "expire_year": 2031,    "ccv": "106",    "security_answer": null,    "direct_deposit_number": null,    "insight_prod_settings": null,    "created_dt": null,    "status": 0,    "Errors": [      "The card number does not match for the selected card type",      "An error occurred during PostCustomerCard: Customer card validation failed."    ],    "billing_zip_code": null,    "card_processor_type": 0,    "CardProcessor": "None",    "CardTokens": null,    "is_existing": false,    "is_active": false  }
18:05:45  END RequestId: 1f60973f-5546-4269-a285-b77d4bb49764
18:05:45  REPORT RequestId: 1f60973f-5546-4269-a285-b77d4bb49764	Duration: 118.93 ms	Billed Duration: 119 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	
18:05:49  START RequestId: 2432f238-9899-4725-ba81-c4cb6397b5e5 Version: $LATEST
18:05:49  [INFO]	2026-04-22T18:05:49.242Z	2432f238-9899-4725-ba81-c4cb6397b5e5	add card attempt cid=601488 last4=0295 brand=Visa exp=04/2031
18:05:49  [WARNING]	2026-04-22T18:05:49.348Z	2432f238-9899-4725-ba81-c4cb6397b5e5	Vergent POST https://shared.vergentlms.com/api/api/V1/PostCustomerCard -> 400: {
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
18:05:49  [WARNING]	2026-04-22T18:05:49.348Z	2432f238-9899-4725-ba81-c4cb6397b5e5	PostCustomerCard upstream status=400 body={'id': 0, 'company_id': 386, 'customer_id': 601488, 'card_type_id': 1, 'card_holder': 'Harut Darakchyan', 'card_number': '****0295', 'card_id': '', 'card_ref': '', 'is_eligible_for_disbursement': False, 'expire_month': 4, 'expire_year': 2031, 'ccv': '***'} raw={    "id": 0,    "company_id": 386,    "customer_id": 601488,    "card_type_id": 1,    "card_holder": "Harut Darakchyan",    "card_number": "4833160326650295",    "card_id": "",    "card_ref": "",    "is_eligible_for_disbursement": false,    "card_account_guid": null,    "card_guid": null,    "last_four_digits": null,    "product_id": 0,    "expire_month": 4,    "expire_year": 2031,    "ccv": "106",    "security_answer": null,    "direct_deposit_number": null,    "insight_prod_settings": null,    "created_dt": null,    "status": 0,    "Errors": [      "The card number does not match for the selected card type",      "An error occurred during PostCustomerCard: Customer card validation failed."    ],    "billing_zip_code": null,    "card_processor_type": 0,    "CardProcessor": "None",    "CardTokens": null,    "is_existing": false,    "is_active": false  }
18:05:49  END RequestId: 2432f238-9899-4725-ba81-c4cb6397b5e5
18:05:49  REPORT RequestId: 2432f238-9899-4725-ba81-c4cb6397b5e5	Duration: 107.67 ms	Billed Duration: 108 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	
18:05:51  START RequestId: 6306e708-d7a3-4fc5-9632-b5665775048f Version: $LATEST
18:05:51  [INFO]	2026-04-22T18:05:51.642Z	6306e708-d7a3-4fc5-9632-b5665775048f	add card attempt cid=601488 last4=0295 brand=Visa exp=04/2031
18:05:51  [WARNING]	2026-04-22T18:05:51.729Z	6306e708-d7a3-4fc5-9632-b5665775048f	Vergent POST https://shared.vergentlms.com/api/api/V1/PostCustomerCard -> 400: {
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
18:05:51  [WARNING]	2026-04-22T18:05:51.729Z	6306e708-d7a3-4fc5-9632-b5665775048f	PostCustomerCard upstream status=400 body={'id': 0, 'company_id': 386, 'customer_id': 601488, 'card_type_id': 1, 'card_holder': 'Harut Darakchyan', 'card_number': '****0295', 'card_id': '', 'card_ref': '', 'is_eligible_for_disbursement': False, 'expire_month': 4, 'expire_year': 2031, 'ccv': '***'} raw={    "id": 0,    "company_id": 386,    "customer_id": 601488,    "card_type_id": 1,    "card_holder": "Harut Darakchyan",    "card_number": "4833160326650295",    "card_id": "",    "card_ref": "",    "is_eligible_for_disbursement": false,    "card_account_guid": null,    "card_guid": null,    "last_four_digits": null,    "product_id": 0,    "expire_month": 4,    "expire_year": 2031,    "ccv": "106",    "security_answer": null,    "direct_deposit_number": null,    "insight_prod_settings": null,    "created_dt": null,    "status": 0,    "Errors": [      "The card number does not match for the selected card type",      "An error occurred during PostCustomerCard: Customer card validation failed."    ],    "billing_zip_code": null,    "card_processor_type": 0,    "CardProcessor": "None",    "CardTokens": null,    "is_existing": false,    "is_active": false  }
18:05:51  END RequestId: 6306e708-d7a3-4fc5-9632-b5665775048f
18:05:51  REPORT RequestId: 6306e708-d7a3-4fc5-9632-b5665775048f	Duration: 88.84 ms	Billed Duration: 89 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	
```
