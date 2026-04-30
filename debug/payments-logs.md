# Payments Lambda logs

- Function: `cif-portal-payments-dev`
- Window: last 30 minute(s)
- Filter: `(none)`
- Captured at: 2026-04-30T20:10:32Z

## 394 event(s)

```
20:07:47  INIT_START Runtime Version: python:3.12.mainlinev2.v7	Runtime Version ARN: arn:aws:lambda:us-east-1::runtime:2b830756c5b10ff133ebda3f21aaa7e31ccd9f7038e1342adb459865da7617a3
20:07:47  [INFO]	2026-04-30T20:07:47.959Z		Found credentials in environment variables.
20:07:48  START RequestId: 47534fdc-8470-4cab-b5f0-5be8a641fb13 Version: $LATEST
20:07:48  [WARNING]	2026-04-30T20:07:48.380Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.380Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens auth=Authorization body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.408Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.408Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens auth=Authorization body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.428Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.428Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens auth=Authorization body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.455Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.455Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens auth=Authorization body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.481Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.482Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens auth=X-API-Key body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.508Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.508Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens auth=X-API-Key body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.528Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.528Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens auth=X-API-Key body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.563Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.563Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens auth=X-API-Key body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.588Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.588Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens auth=apikey body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.608Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.608Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens auth=apikey body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.634Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.634Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens auth=apikey body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.663Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.663Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens auth=apikey body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.688Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.688Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens auth=X-Auth-Token body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.708Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.708Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens auth=X-Auth-Token body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.733Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.734Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens auth=X-Auth-Token body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.768Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.768Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens auth=X-Auth-Token body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.788Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.788Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/sessions auth=Authorization body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.815Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.815Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/sessions auth=Authorization body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.834Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.835Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/sessions auth=Authorization body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.864Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.864Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/sessions auth=Authorization body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.888Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.888Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/sessions auth=X-API-Key body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.915Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.915Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/sessions auth=X-API-Key body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.940Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.940Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/sessions auth=X-API-Key body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.968Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.968Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/sessions auth=X-API-Key body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:48  [WARNING]	2026-04-30T20:07:48.988Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:07:48  [INFO]	2026-04-30T20:07:48.988Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/sessions auth=apikey body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.016Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.016Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/sessions auth=apikey body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.034Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.035Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/sessions auth=apikey body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.068Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.068Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/sessions auth=apikey body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.093Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.093Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/sessions auth=X-Auth-Token body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.121Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.121Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/sessions auth=X-Auth-Token body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.148Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.148Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/sessions auth=X-Auth-Token body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.174Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.174Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/sessions auth=X-Auth-Token body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.198Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.198Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=Authorization body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.228Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.228Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=Authorization body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.252Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.252Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=Authorization body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.279Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.279Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=Authorization body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.300Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.300Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=X-API-Key body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.328Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.328Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=X-API-Key body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.348Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.348Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=X-API-Key body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.379Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.379Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=X-API-Key body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.408Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.408Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=apikey body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.428Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.428Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=apikey body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.453Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.453Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=apikey body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.480Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.481Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=apikey body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.508Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.508Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=X-Auth-Token body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.533Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.533Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=X-Auth-Token body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.568Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.568Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=X-Auth-Token body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.588Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.588Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=X-Auth-Token body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.614Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.614Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/sessions auth=Authorization body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.639Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.639Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/sessions auth=Authorization body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.668Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.668Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/sessions auth=Authorization body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.688Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.688Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/sessions auth=Authorization body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.714Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.714Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/sessions auth=X-API-Key body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.748Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.748Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/sessions auth=X-API-Key body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.768Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.768Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/sessions auth=X-API-Key body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.793Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.793Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/sessions auth=X-API-Key body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.828Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.828Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/sessions auth=apikey body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.853Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.853Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/sessions auth=apikey body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.873Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.873Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/sessions auth=apikey body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.901Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.901Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/sessions auth=apikey body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.928Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.928Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/sessions auth=X-Auth-Token body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.948Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.948Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/sessions auth=X-Auth-Token body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:49  [WARNING]	2026-04-30T20:07:49.973Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:07:49  [INFO]	2026-04-30T20:07:49.974Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/sessions auth=X-Auth-Token body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.001Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.001Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/v1/sessions auth=X-Auth-Token body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.028Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.028Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=Authorization body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.054Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.054Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=Authorization body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.077Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.077Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=Authorization body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.108Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.108Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=Authorization body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.128Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.128Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=X-API-Key body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.153Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.153Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=X-API-Key body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.183Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.183Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=X-API-Key body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.208Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.208Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=X-API-Key body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.228Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.228Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=apikey body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.254Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.254Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=apikey body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.273Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.273Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=apikey body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.308Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.308Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=apikey body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.334Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.334Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=X-Auth-Token body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.358Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.358Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=X-Auth-Token body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.381Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.381Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=X-Auth-Token body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.408Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.408Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=X-Auth-Token body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.436Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.437Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=Authorization body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.459Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.459Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=Authorization body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.488Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.488Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=Authorization body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.513Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.513Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=Authorization body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.534Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.534Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=X-API-Key body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.561Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.561Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=X-API-Key body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.580Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.581Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=X-API-Key body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.608Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.608Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=X-API-Key body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.636Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.636Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=apikey body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.662Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.662Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=apikey body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.688Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.688Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=apikey body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.713Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.713Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=apikey body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.748Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.748Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=X-Auth-Token body=minimal status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.768Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.768Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=X-Auth-Token body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.788Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.788Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=X-Auth-Token body=snake status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.814Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:07:50  [INFO]	2026-04-30T20:07:50.814Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=X-Auth-Token body=merchant status=404 parsed_keys=NoneType raw_head=''
20:07:50  [WARNING]	2026-04-30T20:07:50.814Z	47534fdc-8470-4cab-b5f0-5be8a641fb13	omniapay session creation: no candidate combo worked
20:07:50  END RequestId: 47534fdc-8470-4cab-b5f0-5be8a641fb13
20:07:50  REPORT RequestId: 47534fdc-8470-4cab-b5f0-5be8a641fb13	Duration: 2767.78 ms	Billed Duration: 3157 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	Init Duration: 388.36 ms	
20:08:32  START RequestId: 2971b1fe-6026-4d92-8f82-a25f8cd106f5 Version: $LATEST
20:08:32  [WARNING]	2026-04-30T20:08:32.559Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:08:32  [INFO]	2026-04-30T20:08:32.559Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens auth=Authorization body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:32  [WARNING]	2026-04-30T20:08:32.584Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:08:32  [INFO]	2026-04-30T20:08:32.584Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens auth=Authorization body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:32  [WARNING]	2026-04-30T20:08:32.608Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:08:32  [INFO]	2026-04-30T20:08:32.608Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens auth=Authorization body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:32  [WARNING]	2026-04-30T20:08:32.628Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:08:32  [INFO]	2026-04-30T20:08:32.628Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens auth=Authorization body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:32  [WARNING]	2026-04-30T20:08:32.654Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:08:32  [INFO]	2026-04-30T20:08:32.654Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens auth=X-API-Key body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:32  [WARNING]	2026-04-30T20:08:32.682Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:08:32  [INFO]	2026-04-30T20:08:32.682Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens auth=X-API-Key body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:32  [WARNING]	2026-04-30T20:08:32.708Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:08:32  [INFO]	2026-04-30T20:08:32.708Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens auth=X-API-Key body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:32  [WARNING]	2026-04-30T20:08:32.728Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:08:32  [INFO]	2026-04-30T20:08:32.728Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens auth=X-API-Key body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:32  [WARNING]	2026-04-30T20:08:32.753Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:08:32  [INFO]	2026-04-30T20:08:32.753Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens auth=apikey body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:32  [WARNING]	2026-04-30T20:08:32.783Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:08:32  [INFO]	2026-04-30T20:08:32.784Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens auth=apikey body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:32  [WARNING]	2026-04-30T20:08:32.808Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:08:32  [INFO]	2026-04-30T20:08:32.808Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens auth=apikey body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:32  [WARNING]	2026-04-30T20:08:32.828Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:08:32  [INFO]	2026-04-30T20:08:32.828Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens auth=apikey body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:32  [WARNING]	2026-04-30T20:08:32.848Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:08:32  [INFO]	2026-04-30T20:08:32.848Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens auth=X-Auth-Token body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:32  [WARNING]	2026-04-30T20:08:32.883Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:08:32  [INFO]	2026-04-30T20:08:32.883Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens auth=X-Auth-Token body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:32  [WARNING]	2026-04-30T20:08:32.908Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:08:32  [INFO]	2026-04-30T20:08:32.908Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens auth=X-Auth-Token body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:32  [WARNING]	2026-04-30T20:08:32.928Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens -> 404: 
20:08:32  [INFO]	2026-04-30T20:08:32.928Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens auth=X-Auth-Token body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:32  [WARNING]	2026-04-30T20:08:32.954Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:08:32  [INFO]	2026-04-30T20:08:32.954Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/sessions auth=Authorization body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:32  [WARNING]	2026-04-30T20:08:32.978Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:08:32  [INFO]	2026-04-30T20:08:32.978Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/sessions auth=Authorization body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.001Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.001Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/sessions auth=Authorization body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.028Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.028Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/sessions auth=Authorization body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.048Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.048Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/sessions auth=X-API-Key body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.077Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.077Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/sessions auth=X-API-Key body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.108Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.108Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/sessions auth=X-API-Key body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.128Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.128Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/sessions auth=X-API-Key body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.148Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.148Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/sessions auth=apikey body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.182Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.182Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/sessions auth=apikey body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.208Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.208Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/sessions auth=apikey body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.233Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.233Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/sessions auth=apikey body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.260Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.261Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/sessions auth=X-Auth-Token body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.288Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.288Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/sessions auth=X-Auth-Token body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.308Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.308Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/sessions auth=X-Auth-Token body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.333Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.334Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/sessions auth=X-Auth-Token body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.362Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.362Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=Authorization body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.382Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.382Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=Authorization body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.408Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.408Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=Authorization body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.428Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.428Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=Authorization body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.453Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.453Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=X-API-Key body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.481Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.481Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=X-API-Key body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.508Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.508Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=X-API-Key body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.528Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.528Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=X-API-Key body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.548Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.548Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=apikey body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.581Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.581Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=apikey body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.608Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.608Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=apikey body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.628Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.628Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=apikey body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.654Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.654Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=X-Auth-Token body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.688Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.688Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=X-Auth-Token body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.708Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.708Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=X-Auth-Token body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.733Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/cardtokens -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.734Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/cardtokens auth=X-Auth-Token body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.759Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.760Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/sessions auth=Authorization body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.788Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.788Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/sessions auth=Authorization body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.808Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.808Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/sessions auth=Authorization body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.836Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.837Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/sessions auth=Authorization body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.868Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.868Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/sessions auth=X-API-Key body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.888Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.888Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/sessions auth=X-API-Key body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.916Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.916Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/sessions auth=X-API-Key body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.948Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.948Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/sessions auth=X-API-Key body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.968Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.968Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/sessions auth=apikey body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:33  [WARNING]	2026-04-30T20:08:33.994Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:08:33  [INFO]	2026-04-30T20:08:33.994Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/sessions auth=apikey body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.016Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.017Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/sessions auth=apikey body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.041Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.041Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/sessions auth=apikey body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.068Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.068Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/sessions auth=X-Auth-Token body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.088Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.088Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/sessions auth=X-Auth-Token body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.114Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.114Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/sessions auth=X-Auth-Token body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.148Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/v1/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.148Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/v1/sessions auth=X-Auth-Token body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.168Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.168Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=Authorization body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.188Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.188Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=Authorization body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.217Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.217Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=Authorization body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.241Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.241Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=Authorization body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.268Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.268Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=X-API-Key body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.288Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.288Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=X-API-Key body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.313Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.313Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=X-API-Key body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.342Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.342Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=X-API-Key body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.360Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.360Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=apikey body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.388Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.388Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=apikey body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.408Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.408Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=apikey body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.437Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.437Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=apikey body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.459Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.459Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=X-Auth-Token body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.479Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.479Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=X-Auth-Token body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.508Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.508Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=X-Auth-Token body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.528Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/iframe/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.528Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/iframe/sessions auth=X-Auth-Token body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.558Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.558Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=Authorization body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.580Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.580Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=Authorization body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.608Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.608Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=Authorization body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.628Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.628Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=Authorization body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.654Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.654Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=X-API-Key body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.681Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.681Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=X-API-Key body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.700Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.700Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=X-API-Key body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.728Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.728Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=X-API-Key body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.748Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.748Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=apikey body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.774Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.774Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=apikey body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.808Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.808Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=apikey body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.828Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.828Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=apikey body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.854Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.854Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=X-Auth-Token body=minimal status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.882Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.882Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=X-Auth-Token body=with_customer status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.900Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.900Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=X-Auth-Token body=snake status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.928Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	Vergent POST https://api.omniapay.com/cardtokens/sessions -> 404: 
20:08:34  [INFO]	2026-04-30T20:08:34.928Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay probe url=https://api.omniapay.com/cardtokens/sessions auth=X-Auth-Token body=merchant status=404 parsed_keys=NoneType raw_head=''
20:08:34  [WARNING]	2026-04-30T20:08:34.928Z	2971b1fe-6026-4d92-8f82-a25f8cd106f5	omniapay session creation: no candidate combo worked
20:08:34  END RequestId: 2971b1fe-6026-4d92-8f82-a25f8cd106f5
20:08:34  REPORT RequestId: 2971b1fe-6026-4d92-8f82-a25f8cd106f5	Duration: 2384.96 ms	Billed Duration: 2385 ms	Memory Size: 256 MB	Max Memory Used: 89 MB	
```
