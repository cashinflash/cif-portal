# Lambda logs — cif-portal-auth-mfa-dev

- Function: `cif-portal-auth-mfa-dev`
- Window: last 30 minute(s)
- Filter: `(none)`
- Captured at: 2026-04-22T21:03:25Z

## 8 event(s)

```
20:59:33  INIT_START Runtime Version: python:3.12.mainlinev2.v7	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:2b830756c5b10ff133ebda3f21aaa7e31ccd9f7038e1342adb459865da7617a3
20:59:33  START RequestId: c9e99b78-bb87-4c49-b5ea-b9755c6da5d6 Version: $LATEST
20:59:36  END RequestId: c9e99b78-bb87-4c49-b5ea-b9755c6da5d6
20:59:36  REPORT RequestId: c9e99b78-bb87-4c49-b5ea-b9755c6da5d6	Duration: 2644.11 ms	Billed Duration: 3265 ms	Memory Size: 256 MB	Max Memory Used: 97 MB	Init Duration: 620.29 ms	
XRAY TraceId: 1-69e936b4-2e0935296e44810b7c266bb0	SegmentId: 795a277df463c283	Sampled: true	
20:59:39  START RequestId: 74001d7e-89a5-447e-902b-6b57ffb1d16d Version: $LATEST
20:59:39  [ERROR]	2026-04-22T20:59:39.268Z	74001d7e-89a5-447e-902b-6b57ffb1d16d	SES send_email failed: Source=Cash in Flash <noreply@cashinflash.com> to=harut@ymail.com code=MessageRejected type=Sender msg=Email address is not verified. The following identities failed the check in region US-EAST-1: harut@ymail.com
20:59:39  END RequestId: 74001d7e-89a5-447e-902b-6b57ffb1d16d
20:59:39  REPORT RequestId: 74001d7e-89a5-447e-902b-6b57ffb1d16d	Duration: 213.51 ms	Billed Duration: 214 ms	Memory Size: 256 MB	Max Memory Used: 98 MB	
XRAY TraceId: 1-69e936bb-58dcadf60b86ff2316216ef6	SegmentId: f69db1e0403e34d3	Sampled: true	
```
