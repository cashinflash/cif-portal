# IF endpoint diagnostic

_Captured at: 2026-04-22T22:43:36Z_

## 1. Lambda existence + handler path

- Exists: **YES**
- Handler: `handlers.if_submit.lambda_handler`
- Runtime: `python3.12`  Arch: `arm64`  State: `Active`
- Last modified: `2026-04-22T22:16:58.000+0000`
- Env var keys: `IF_DDB_TABLE, IF_KMS_KEY_ID, IF_NOTIFY_EMAIL, IF_VIEW_SHARED_SECRET, IF_VIEW_URL_BASE, MFA_EMAIL_SENDER`

## 2. HttpApi routes matching /api/if/*
```
---------------------------------------------------------------
|                          GetRoutes                          |
+------+-----------------------------+------------------------+
| Auth |            Route            |        Target          |
+------+-----------------------------+------------------------+
|  NONE|  OPTIONS /api/if/list       |  integrations/2mvwbsf  |
|  NONE|  GET /api/if/view/{id}      |  integrations/2mvwbsf  |
|  NONE|  GET /api/if/list           |  integrations/2mvwbsf  |
|  NONE|  OPTIONS /api/if/view/{id}  |  integrations/2mvwbsf  |
|  NONE|  POST /api/if/submit        |  integrations/2mvwbsf  |
|  NONE|  OPTIONS /api/if/submit     |  integrations/2mvwbsf  |
+------+-----------------------------+------------------------+
```

## 3. Integration → function mapping
```
----------------------------------------------------------------------------------------
|                                    GetIntegrations                                   |
+----------------+---------------------------------------------------------------------+
|  IntegrationId |  2mvwbsf                                                            |
|  PayloadVersion|  2.0                                                                |
|  Uri           |  arn:aws:lambda:us-east-1:730667140069:function:cif-portal-if-dev   |
+----------------+---------------------------------------------------------------------+
```

## 4. Live POST to /api/if/submit (bad body on purpose)
- Endpoint: `https://anh066l1wf.execute-api.us-east-1.amazonaws.com/api/if/submit`
- HTTP status: `404`
- Response body:
```
{"message":"Not Found"}
```

## 5. Live OPTIONS preflight (what the browser does first)
- Preflight status: `404`
- Preflight response headers + body (if any):
```
HTTP/2 404 
date: Wed, 22 Apr 2026 22:43:40 GMT
content-type: application/json
content-length: 23
apigw-requestid: cPlMih7_oAMEbcw=

```
