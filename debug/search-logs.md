# Lambda logs — cif-portal-search-dev

- Function: `cif-portal-search-dev`
- Window: last 30 minute(s)
- Filter: `(none)`
- Captured at: 2026-04-22T21:04:12Z

## 10 event(s)

```
21:00:54  INIT_START Runtime Version: python:3.12.mainlinev2.v7	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:2b830756c5b10ff133ebda3f21aaa7e31ccd9f7038e1342adb459865da7617a3
21:00:55  [WARNING]	2026-04-22T21:00:55.004Z		LAMBDA_WARNING: Unhandled exception. The most likely cause is an issue in the function code. However, in rare cases, a Lambda runtime update can cause unexpected function behavior. For functions using managed runtimes, runtime updates can be triggered by a function change, or can be applied automatically. To determine if the runtime has been updated, check the runtime version in the INIT_START log entry. If this error correlates with a change in the runtime version, you may be able to mitigate this error by temporarily rolling back to the previous runtime version. For more information, see https://docs.aws.amazon.com/lambda/latest/dg/runtimes-update.html
21:00:55  [ERROR] Runtime.ImportModuleError: Unable to import module 'search': No module named 'search'
Traceback (most recent call last):
21:00:55  INIT_REPORT Init Duration: 137.69 ms	Phase: init	Status: error	Error Type: Runtime.ImportModuleError
21:00:55  [WARNING]	2026-04-22T21:00:55.118Z		LAMBDA_WARNING: Unhandled exception. The most likely cause is an issue in the function code. However, in rare cases, a Lambda runtime update can cause unexpected function behavior. For functions using managed runtimes, runtime updates can be triggered by a function change, or can be applied automatically. To determine if the runtime has been updated, check the runtime version in the INIT_START log entry. If this error correlates with a change in the runtime version, you may be able to mitigate this error by temporarily rolling back to the previous runtime version. For more information, see https://docs.aws.amazon.com/lambda/latest/dg/runtimes-update.html
21:00:55  [ERROR] Runtime.ImportModuleError: Unable to import module 'search': No module named 'search'
Traceback (most recent call last):
21:00:55  INIT_REPORT Init Duration: 80.49 ms	Phase: invoke	Status: error	Error Type: Runtime.ImportModuleError
21:00:55  START RequestId: 12131914-ade7-4b3b-adbf-f01e971190d5 Version: $LATEST
21:00:55  END RequestId: 12131914-ade7-4b3b-adbf-f01e971190d5
21:00:55  REPORT RequestId: 12131914-ade7-4b3b-adbf-f01e971190d5	Duration: 98.71 ms	Billed Duration: 99 ms	Memory Size: 512 MB	Max Memory Used: 46 MB	Status: error	Error Type: Runtime.ImportModuleError
```
