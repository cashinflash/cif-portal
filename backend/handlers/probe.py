"""Probe: narrow down the correct userType + businessName combo for consumer search."""

import json
import urllib.error
import urllib.request
import aws_secrets
from responses import ok


URL = "https://prod.apim.vergentlms.com/external/shared/api/CustomerPortal/Customer/Search"


def _try(api_key, body):
    headers = {"x-api-key": api_key, "Accept": "application/json",
               "Content-Type": "application/json-patch+json"}
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(URL, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"status": resp.status, "body": resp.read().decode("utf-8", errors="replace")[:300]}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "body": (e.read() or b"").decode("utf-8", errors="replace")[:300]}


def lambda_handler(event, context):
    key = aws_secrets.load("cif-portal/vergent/credentials").get("xApiKey", "")
    base = {
        "firstName": "John",
        "lastName": "Doe",
        "birthDate": "1990-01-01T00:00:00Z",
        "phoneNumber": "5555555555",
        "idNumber": "123456789",
        "einNumber": "",
    }
    scenarios = {
        "userType_0_no_biz":     {**base, "businessName": "",     "userType": 0},
        "userType_1_no_biz":     {**base, "businessName": "",     "userType": 1},
        "userType_2_no_biz":     {**base, "businessName": "",     "userType": 2},
        "userType_0_biz_na":     {**base, "businessName": "N/A",  "userType": 0},
        "userType_1_biz_na":     {**base, "businessName": "N/A",  "userType": 1},
        "omit_biz_userType_0":   {k: v for k, v in {**base, "userType": 0}.items() if k != "businessName"},
        "omit_biz_userType_1":   {k: v for k, v in {**base, "userType": 1}.items() if k != "businessName"},
    }
    results = {}
    for label, body in scenarios.items():
        results[label] = _try(key, body)
    return ok(results, status=200)
