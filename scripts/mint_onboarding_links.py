#!/usr/bin/env python3
"""Mint one-click portal onboarding links (magic links).

Each link lets an existing customer set a password and land in the portal in
one click — no email code — because holding the link proves they control the
inbox it was sent to. Feed the output URLs to your email tool as the
"Register Now" button per customer.

The token is HMAC-signed with the same secret the auth-mfa Lambda verifies
against (Secrets Manager: cif-portal/onboard-signing-secret), so this must run
with AWS credentials that can read that secret (e.g. AWS CloudShell).

Token format (matches auth_mfa.py _verify_onboard):
    base64url(payload_json) + "." + base64url(hmac_sha256(payload_json, secret))
    payload = {"cid","email","fn","ln","exp"}   # exp = unix seconds

Usage:
  # one customer (test):
  python mint_onboarding_links.py --cid 601488 --email a@b.com --first Harut --last D

  # batch from a CSV with header: cid,email,firstName,lastName
  python mint_onboarding_links.py --csv customers.csv --out links.csv

  # options:
  --origin   portal origin (default https://d1zucrj1ouu3c.cloudfront.net)
  --exp-days link lifetime in days (default 14)
"""
import argparse
import base64
import csv
import hashlib
import hmac
import json
import sys
import time

import boto3

SECRET_NAME_DEFAULT = "cif-portal/onboard-signing-secret"
ORIGIN_DEFAULT = "https://d1zucrj1ouu3c.cloudfront.net"


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def load_secret(secret_name: str, region: str) -> bytes:
    sm = boto3.client("secretsmanager", region_name=region)
    raw = sm.get_secret_value(SecretId=secret_name).get("SecretString") or ""
    val = raw
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            val = obj.get("secret") or obj.get("value") or ""
    except Exception:
        pass
    if not val:
        raise SystemExit("ERROR: onboarding secret is empty")
    return val.encode("utf-8")


def mint(secret: bytes, *, cid: str, email: str, first: str, last: str,
         exp: int, origin: str) -> str:
    payload = {"cid": str(cid), "email": email.strip().lower(),
               "fn": first or "", "ln": last or "", "exp": int(exp)}
    body = _b64u(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = _b64u(hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest())
    token = body + "." + sig
    return f"{origin.rstrip('/')}/onboard.html#t={token}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Mint portal onboarding magic links")
    ap.add_argument("--csv", help="CSV with header: cid,email,firstName,lastName")
    ap.add_argument("--out", help="write email,url rows here (default: stdout)")
    ap.add_argument("--cid")
    ap.add_argument("--email")
    ap.add_argument("--first", default="")
    ap.add_argument("--last", default="")
    ap.add_argument("--origin", default=ORIGIN_DEFAULT)
    ap.add_argument("--exp-days", type=int, default=14)
    ap.add_argument("--secret-name", default=SECRET_NAME_DEFAULT)
    ap.add_argument("--region", default="us-east-1")
    args = ap.parse_args()

    secret = load_secret(args.secret_name, args.region)
    exp = int(time.time()) + args.exp_days * 86400

    rows = []
    if args.csv:
        with open(args.csv, newline="") as f:
            for r in csv.DictReader(f):
                cid = (r.get("cid") or r.get("customerId") or "").strip()
                email = (r.get("email") or "").strip()
                if not cid or not email:
                    continue
                rows.append((cid, email, (r.get("firstName") or "").strip(),
                             (r.get("lastName") or "").strip()))
    elif args.cid and args.email:
        rows.append((args.cid, args.email, args.first, args.last))
    else:
        ap.error("provide --csv, or --cid and --email")

    out = open(args.out, "w", newline="") if args.out else sys.stdout
    w = csv.writer(out)
    w.writerow(["email", "url"])
    for cid, email, first, last in rows:
        w.writerow([email, mint(secret, cid=cid, email=email, first=first,
                                last=last, exp=exp, origin=args.origin)])
    if args.out:
        out.close()
        print(f"Wrote {len(rows)} link(s) to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
