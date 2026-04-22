# Payments Lambda logs

- Function: `cif-portal-payments-dev`
- Window: last 30 minute(s)
- Filter: `(none)`
- Captured at: 2026-04-22T04:08:16Z

## 55 event(s)

```
03:58:39  INIT_START Runtime Version: python:3.12.mainlinev2.v7	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:2b830756c5b10ff133ebda3f21aaa7e31ccd9f7038e1342adb459865da7617a3
03:58:39  INIT_START Runtime Version: python:3.12.mainlinev2.v7	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:2b830756c5b10ff133ebda3f21aaa7e31ccd9f7038e1342adb459865da7617a3
03:58:39  [INFO]	2026-04-22T03:58:39.376Z		Found credentials in environment variables.
03:58:39  [INFO]	2026-04-22T03:58:39.423Z		Found credentials in environment variables.
03:58:39  START RequestId: 80fbc1aa-ea4f-431a-9bc4-ad1e42af3b79 Version: $LATEST
03:58:39  START RequestId: f6734590-c66a-4424-8ea2-391a5d8d4f11 Version: $LATEST
03:58:39  [INFO]	2026-04-22T03:58:39.886Z	80fbc1aa-ea4f-431a-9bc4-ad1e42af3b79	v1 service Token cached (3600s) userId=8434
03:58:40  [WARNING]	2026-04-22T03:58:40.345Z	f6734590-c66a-4424-8ea2-391a5d8d4f11	Vergent GET https://prod.apim.vergentlms.com/external/shared/api/CustomerPortal/Customer/Cards -> 400: "The customer info could not be retrieved."
03:58:40  [WARNING]	2026-04-22T03:58:40.346Z	f6734590-c66a-4424-8ea2-391a5d8d4f11	Customer/Cards status=400 raw="The customer info could not be retrieved."
03:58:40  END RequestId: f6734590-c66a-4424-8ea2-391a5d8d4f11
03:58:40  REPORT RequestId: f6734590-c66a-4424-8ea2-391a5d8d4f11	Duration: 771.53 ms	Billed Duration: 1278 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	Init Duration: 505.79 ms	
03:58:40  [INFO]	2026-04-22T03:58:40.572Z	80fbc1aa-ea4f-431a-9bc4-ad1e42af3b79	autopay probe hdr_id=4823221 hdr_keys=['AchOptOut', 'AmountDue', 'ChannelId', 'CompanyId', 'CosignerId', 'CustomerId', 'DueDate', 'Errors', 'FundingDate', 'HeldBankAccountId', 'HeldCheckNumber', 'InitialLoanStatus', 'IsEligibleForRefi', 'IsInRescindPeriod', 'IsStatusOutstanding', 'LoanAmount', 'LoanClassId', 'LoanModelId', 'LoanModelName', 'LoanTypeName', 'LocCreditLimit', 'MinAmountDue', 'MinLoanAmount', 'NumberOfPayments', 'OriginationDate', 'PaymentBankAccountId', 'PayoffAmount', 'PrinPerPayment', 'PrinReduction', 'RPP', 'RescindEndDate', 'RescindType', 'RescindValue', 'StatusId', 'StoreId', 'SubStatusId', 'ToCustomer', 'adv_trans_id', 'hdr_id', 'original_hdr_id', 'prev_hdr_id', 'prev_sys_id', 'product_root_hdr_id', 'root_hdr_id'] detail_keys=['AccountNum', 'AutoPayCardId', 'AutoPayMethod', 'AvailableCredit', 'Balance', 'CreditLimit', 'DaysLate', 'EarnedFees', 'EarnedPrin', 'Errors', 'FeeBalance', 'IRepoStatus', 'IsAutoPay', 'IsSoftVoid', 'LastPmtDate', 'Lender', 'LoanModelName', 'PaidOffDate', 'PastDueAmount', 'PrinBalance', 'PublicLoanId', 'Recent', 'StateDbId', 'Status', 'StoreName', 'SubStatus', 'SuretyBondCo', 'Tags']
03:58:40  END RequestId: 80fbc1aa-ea4f-431a-9bc4-ad1e42af3b79
03:58:40  REPORT RequestId: 80fbc1aa-ea4f-431a-9bc4-ad1e42af3b79	Duration: 1038.94 ms	Billed Duration: 1523 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	Init Duration: 483.11 ms	
03:59:05  START RequestId: ab21da63-66ba-49ae-8871-361e8df804a5 Version: $LATEST
03:59:05  [INFO]	2026-04-22T03:59:05.682Z	ab21da63-66ba-49ae-8871-361e8df804a5	add card attempt cid=601488 last4=6437 brand=MasterCard exp=08/2030
03:59:06  [WARNING]	2026-04-22T03:59:06.105Z	ab21da63-66ba-49ae-8871-361e8df804a5	Vergent POST https://prod.apim.vergentlms.com/external/shared/api/CustomerPortal/Customer/Cards -> 400: {"ClassName":"System.Exception","Message":"No customer identifier could be found from the mobile profile id:8434","Data":null,"InnerException":null,"HelpURL":null,"StackTraceString":"   at Vergent.Lms.Api.CustomerPortal.Domain.Implementation.CustomerPaymentDomain.GetCustomerIdAsync(UInt32 mobileProf
03:59:06  [WARNING]	2026-04-22T03:59:06.105Z	ab21da63-66ba-49ae-8871-361e8df804a5	add card upstream status=400 raw={"ClassName":"System.Exception","Message":"No customer identifier could be found from the mobile profile id:8434","Data":null,"InnerException":null,"HelpURL":null,"StackTraceString":"   at Vergent.Lms.Api.CustomerPortal.Domain.Implementation.CustomerPaymentDomain.GetCustomerIdAsync(UInt32 mobileProf
03:59:06  END RequestId: ab21da63-66ba-49ae-8871-361e8df804a5
03:59:06  REPORT RequestId: ab21da63-66ba-49ae-8871-361e8df804a5	Duration: 425.30 ms	Billed Duration: 426 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	
03:59:12  START RequestId: 8ea2f670-74b5-444d-a5fd-0e8a79999a2f Version: $LATEST
03:59:12  [INFO]	2026-04-22T03:59:12.008Z	8ea2f670-74b5-444d-a5fd-0e8a79999a2f	add card attempt cid=601488 last4=6437 brand=MasterCard exp=08/2030
03:59:12  [WARNING]	2026-04-22T03:59:12.198Z	8ea2f670-74b5-444d-a5fd-0e8a79999a2f	Vergent POST https://prod.apim.vergentlms.com/external/shared/api/CustomerPortal/Customer/Cards -> 400: {"ClassName":"System.Exception","Message":"No customer identifier could be found from the mobile profile id:8434","Data":null,"InnerException":null,"HelpURL":null,"StackTraceString":"   at Vergent.Lms.Api.CustomerPortal.Domain.Implementation.CustomerPaymentDomain.GetCustomerIdAsync(UInt32 mobileProf
03:59:12  [WARNING]	2026-04-22T03:59:12.198Z	8ea2f670-74b5-444d-a5fd-0e8a79999a2f	add card upstream status=400 raw={"ClassName":"System.Exception","Message":"No customer identifier could be found from the mobile profile id:8434","Data":null,"InnerException":null,"HelpURL":null,"StackTraceString":"   at Vergent.Lms.Api.CustomerPortal.Domain.Implementation.CustomerPaymentDomain.GetCustomerIdAsync(UInt32 mobileProf
03:59:12  END RequestId: 8ea2f670-74b5-444d-a5fd-0e8a79999a2f
03:59:12  REPORT RequestId: 8ea2f670-74b5-444d-a5fd-0e8a79999a2f	Duration: 191.73 ms	Billed Duration: 192 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	
03:59:20  START RequestId: 7f2eb9e1-f4f6-4f73-9af4-2a7fb8bc7a3f Version: $LATEST
03:59:20  [WARNING]	2026-04-22T03:59:20.651Z	7f2eb9e1-f4f6-4f73-9af4-2a7fb8bc7a3f	Vergent GET https://prod.apim.vergentlms.com/external/shared/api/CustomerPortal/Customer/Cards -> 400: "The customer info could not be retrieved."
03:59:20  [WARNING]	2026-04-22T03:59:20.651Z	7f2eb9e1-f4f6-4f73-9af4-2a7fb8bc7a3f	Customer/Cards status=400 raw="The customer info could not be retrieved."
03:59:20  END RequestId: 7f2eb9e1-f4f6-4f73-9af4-2a7fb8bc7a3f
03:59:20  REPORT RequestId: 7f2eb9e1-f4f6-4f73-9af4-2a7fb8bc7a3f	Duration: 282.85 ms	Billed Duration: 283 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	
03:59:33  START RequestId: bef56de1-c2b6-4fdd-8e4c-ae879bbf900f Version: $LATEST
03:59:33  START RequestId: 34f3e811-2152-4187-a8a3-78fe93c033c2 Version: $LATEST
03:59:33  [WARNING]	2026-04-22T03:59:33.846Z	34f3e811-2152-4187-a8a3-78fe93c033c2	Vergent GET https://prod.apim.vergentlms.com/external/shared/api/CustomerPortal/Customer/Cards -> 400: "The customer info could not be retrieved."
03:59:33  [WARNING]	2026-04-22T03:59:33.846Z	34f3e811-2152-4187-a8a3-78fe93c033c2	Customer/Cards status=400 raw="The customer info could not be retrieved."
03:59:33  END RequestId: 34f3e811-2152-4187-a8a3-78fe93c033c2
03:59:33  REPORT RequestId: 34f3e811-2152-4187-a8a3-78fe93c033c2	Duration: 191.72 ms	Billed Duration: 192 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	
03:59:34  [INFO]	2026-04-22T03:59:34.507Z	bef56de1-c2b6-4fdd-8e4c-ae879bbf900f	autopay probe hdr_id=4823221 hdr_keys=['AchOptOut', 'AmountDue', 'ChannelId', 'CompanyId', 'CosignerId', 'CustomerId', 'DueDate', 'Errors', 'FundingDate', 'HeldBankAccountId', 'HeldCheckNumber', 'InitialLoanStatus', 'IsEligibleForRefi', 'IsInRescindPeriod', 'IsStatusOutstanding', 'LoanAmount', 'LoanClassId', 'LoanModelId', 'LoanModelName', 'LoanTypeName', 'LocCreditLimit', 'MinAmountDue', 'MinLoanAmount', 'NumberOfPayments', 'OriginationDate', 'PaymentBankAccountId', 'PayoffAmount', 'PrinPerPayment', 'PrinReduction', 'RPP', 'RescindEndDate', 'RescindType', 'RescindValue', 'StatusId', 'StoreId', 'SubStatusId', 'ToCustomer', 'adv_trans_id', 'hdr_id', 'original_hdr_id', 'prev_hdr_id', 'prev_sys_id', 'product_root_hdr_id', 'root_hdr_id'] detail_keys=['AccountNum', 'AutoPayCardId', 'AutoPayMethod', 'AvailableCredit', 'Balance', 'CreditLimit', 'DaysLate', 'EarnedFees', 'EarnedPrin', 'Errors', 'FeeBalance', 'IRepoStatus', 'IsAutoPay', 'IsSoftVoid', 'LastPmtDate', 'Lender', 'LoanModelName', 'PaidOffDate', 'PastDueAmount', 'PrinBalance', 'PublicLoanId', 'Recent', 'StateDbId', 'Status', 'StoreName', 'SubStatus', 'SuretyBondCo', 'Tags']
03:59:34  END RequestId: bef56de1-c2b6-4fdd-8e4c-ae879bbf900f
03:59:34  REPORT RequestId: bef56de1-c2b6-4fdd-8e4c-ae879bbf900f	Duration: 860.66 ms	Billed Duration: 861 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	
03:59:55  START RequestId: ed1349ae-37c0-46e8-8130-99a8e94f42c8 Version: $LATEST
03:59:55  START RequestId: 6169c7c4-27dd-4f9b-8315-7689cf4b87a8 Version: $LATEST
03:59:55  [WARNING]	2026-04-22T03:59:55.381Z	6169c7c4-27dd-4f9b-8315-7689cf4b87a8	Vergent GET https://prod.apim.vergentlms.com/external/shared/api/CustomerPortal/Customer/Cards -> 400: "The customer info could not be retrieved."
03:59:55  [WARNING]	2026-04-22T03:59:55.381Z	6169c7c4-27dd-4f9b-8315-7689cf4b87a8	Customer/Cards status=400 raw="The customer info could not be retrieved."
03:59:55  END RequestId: 6169c7c4-27dd-4f9b-8315-7689cf4b87a8
03:59:55  REPORT RequestId: 6169c7c4-27dd-4f9b-8315-7689cf4b87a8	Duration: 207.40 ms	Billed Duration: 208 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	
03:59:55  [INFO]	2026-04-22T03:59:55.579Z	ed1349ae-37c0-46e8-8130-99a8e94f42c8	autopay probe hdr_id=4823221 hdr_keys=['AchOptOut', 'AmountDue', 'ChannelId', 'CompanyId', 'CosignerId', 'CustomerId', 'DueDate', 'Errors', 'FundingDate', 'HeldBankAccountId', 'HeldCheckNumber', 'InitialLoanStatus', 'IsEligibleForRefi', 'IsInRescindPeriod', 'IsStatusOutstanding', 'LoanAmount', 'LoanClassId', 'LoanModelId', 'LoanModelName', 'LoanTypeName', 'LocCreditLimit', 'MinAmountDue', 'MinLoanAmount', 'NumberOfPayments', 'OriginationDate', 'PaymentBankAccountId', 'PayoffAmount', 'PrinPerPayment', 'PrinReduction', 'RPP', 'RescindEndDate', 'RescindType', 'RescindValue', 'StatusId', 'StoreId', 'SubStatusId', 'ToCustomer', 'adv_trans_id', 'hdr_id', 'original_hdr_id', 'prev_hdr_id', 'prev_sys_id', 'product_root_hdr_id', 'root_hdr_id'] detail_keys=['AccountNum', 'AutoPayCardId', 'AutoPayMethod', 'AvailableCredit', 'Balance', 'CreditLimit', 'DaysLate', 'EarnedFees', 'EarnedPrin', 'Errors', 'FeeBalance', 'IRepoStatus', 'IsAutoPay', 'IsSoftVoid', 'LastPmtDate', 'Lender', 'LoanModelName', 'PaidOffDate', 'PastDueAmount', 'PrinBalance', 'PublicLoanId', 'Recent', 'StateDbId', 'Status', 'StoreName', 'SubStatus', 'SuretyBondCo', 'Tags']
03:59:55  END RequestId: ed1349ae-37c0-46e8-8130-99a8e94f42c8
03:59:55  REPORT RequestId: ed1349ae-37c0-46e8-8130-99a8e94f42c8	Duration: 546.28 ms	Billed Duration: 547 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	
04:00:55  START RequestId: 746a6e13-c57b-499d-b492-d386763398f3 Version: $LATEST
04:00:55  [INFO]	2026-04-22T04:00:55.343Z	746a6e13-c57b-499d-b492-d386763398f3	add card attempt cid=601488 last4=4242 brand=Visa exp=08/2030
04:00:55  [WARNING]	2026-04-22T04:00:55.555Z	746a6e13-c57b-499d-b492-d386763398f3	Vergent POST https://prod.apim.vergentlms.com/external/shared/api/CustomerPortal/Customer/Cards -> 400: {"ClassName":"System.Exception","Message":"No customer identifier could be found from the mobile profile id:8434","Data":null,"InnerException":null,"HelpURL":null,"StackTraceString":"   at Vergent.Lms.Api.CustomerPortal.Domain.Implementation.CustomerPaymentDomain.GetCustomerIdAsync(UInt32 mobileProf
04:00:55  [WARNING]	2026-04-22T04:00:55.556Z	746a6e13-c57b-499d-b492-d386763398f3	add card upstream status=400 raw={"ClassName":"System.Exception","Message":"No customer identifier could be found from the mobile profile id:8434","Data":null,"InnerException":null,"HelpURL":null,"StackTraceString":"   at Vergent.Lms.Api.CustomerPortal.Domain.Implementation.CustomerPaymentDomain.GetCustomerIdAsync(UInt32 mobileProf
04:00:55  END RequestId: 746a6e13-c57b-499d-b492-d386763398f3
04:00:55  REPORT RequestId: 746a6e13-c57b-499d-b492-d386763398f3	Duration: 214.72 ms	Billed Duration: 215 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	
```
