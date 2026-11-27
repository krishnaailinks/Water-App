#!/usr/bin/env python3
"""Register a Maruti Water account for any role, against whichever Supabase
project the app is currently built against.

    python scripts/create_account.py --role owner  --email boss@example.com
    python scripts/create_account.py --role retailer --email shop@example.com \
        --name "Ramesh Patel" --firm "Shree Aqua Sales" --phone 9825012345 \
        --city Rajkot
    python scripts/create_account.py --check          # reach the project, create nothing

Design notes, because they matter more than the flags:

* The project is read out of `config/prod.json` (or `--config`), never
  hard-coded. These files have pointed at two different Supabase projects in
  this repository's history, and an account created against the wrong one
  looks exactly like an account that does not work.

* Registration goes through the public `/auth/v1/signup` endpoint with the
  publishable key -- the same path `SupabaseAuthRepository.signUp` takes. The
  database's own `handle_new_user()` trigger reads `role` out of the signup
  metadata and assigns role and status itself. Nothing here needs the
  `service_role` key, and nothing here writes to `auth.users` directly.

* Per that trigger: owner and retailer land `approved`; a wholesaler lands
  `pending` and cannot see the catalogue until an owner approves it. That is
  the business rule, not a fault, and this script reports it rather than
  working around it.

* Everything is verified by signing in afterwards and reading the profile row
  back, filtered by the new user's id. A profile query without that filter
  returns every row the caller can see -- for an owner, all of them -- so an
  unfiltered read reports a stranger's row as if it were yours.

Requires nothing but Python 3.8+. No pip install.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# 'admin' is not a role in this schema. The administrator is the owner: every
# is_owner() check in the database -- dealer approval, pricing, audit log, the
# owner RPCs -- keys off role = 'owner'.
ROLES = {
    "owner": "owner",
    "admin": "owner",
    "wholesaler": "wholesaler",
    "retailer": "retailer",
}

WORDS = ("river", "copper", "lantern", "mango", "harbour", "cobalt", "pepper",
         "willow", "anchor", "saffron", "quartz", "meadow", "cedar", "indigo",
         "falcon", "basil", "marble", "orchid", "timber", "velvet")


def make_password() -> str:
    """Three words and two digits: easy to read down a phone line, ~51 bits."""
    return "-".join(secrets.choice(WORDS) for _ in range(3)) + \
           "-" + str(secrets.randbelow(90) + 10)


class Api:
    def __init__(self, url: str, key: str) -> None:
        self.url = url.rstrip("/")
        self.key = key

    def call(self, path, body=None, token=None, method=None, prefer=None):
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {token or self.key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        req = urllib.request.Request(
            f"{self.url}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
            method=method or ("POST" if body is not None else "GET"),
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, (json.loads(raw) if raw else {})
            except json.JSONDecodeError:
                return e.code, {"message": raw.decode(errors="replace")[:300]}
        except urllib.error.URLError as e:
            return 0, {"message": f"cannot reach {self.url}: {e.reason}"}

    def login(self, email, password):
        return self.call("/auth/v1/token?grant_type=password",
                         {"email": email, "password": password})


def err_text(body) -> str:
    if not isinstance(body, dict):
        return str(body)
    return (body.get("error_description") or body.get("msg")
            or body.get("message") or body.get("error") or "")


def load_config(path: Path):
    if not path.is_file():
        sys.exit(f"no such config file: {path}")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    for field in ("SUPABASE_URL", "SUPABASE_ANON_KEY"):
        if not cfg.get(field):
            sys.exit(f"{path} has no {field}")
    return cfg["SUPABASE_URL"], cfg["SUPABASE_ANON_KEY"]


def check_project(api: Api) -> bool:
    """Report whether the project is reachable and whether new accounts can
    sign in straight away. Returns False if signup is pointless right now."""
    status, settings = api.call("/auth/v1/settings")
    if status != 200:
        print(f"  auth endpoint: HTTP {status} {err_text(settings)}")
        return False

    autoconfirm = settings.get("mailer_autoconfirm")
    disabled = settings.get("disable_signup")
    print(f"  auth endpoint:     reachable")
    print(f"  signups:           {'DISABLED' if disabled else 'open'}")
    print(f"  email autoconfirm: {'on' if autoconfirm else 'OFF'}")

    if disabled:
        print("\n  Signups are turned off for this project. Turn them on under\n"
              "  Authentication > Sign In / Providers, or create the user in the\n"
              "  dashboard instead.")
        return False
    if not autoconfirm:
        print("\n  Email confirmation is on, so a new account cannot sign in until\n"
              "  the link is clicked -- and the built-in SMTP allows only a couple\n"
              "  of mails an hour. Turn off Confirm email first unless the address\n"
              "  really does receive mail.")
    return True


def main() -> int:
    p = argparse.ArgumentParser(
        description="Register a Maruti Water account for any role.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Roles: owner (admin), wholesaler, retailer. A wholesaler is "
               "created pending and needs an owner to approve it.")
    p.add_argument("--config", default="config/prod.json",
                   help="which build config names the Supabase project "
                        "(default: config/prod.json)")
    p.add_argument("--check", action="store_true",
                   help="report the project's state and exit, creating nothing")
    p.add_argument("--role", choices=sorted(ROLES), help="account role")
    p.add_argument("--email", help="sign-in address")
    p.add_argument("--password",
                   help="leave out and a readable one is generated for you")
    p.add_argument("--name", help="full name (default: the part before the @)")
    p.add_argument("--firm", help="firm name (default: the full name)")
    p.add_argument("--phone", default="", help="10-digit mobile number")
    p.add_argument("--city", default="Botad")
    p.add_argument("--state", default="Gujarat")
    p.add_argument("--gst", help="GST number, written to the profile after signup")
    p.add_argument("--address", help="written to the profile after signup")
    args = p.parse_args()

    url, key = load_config(REPO / args.config)
    api = Api(url, key)

    print(f"project: {url}")
    print(f"config:  {args.config}\n")

    ok = check_project(api)
    if args.check:
        return 0 if ok else 1
    if not ok:
        return 1

    if not args.role or not args.email:
        p.error("--role and --email are required (or use --check)")

    role = ROLES[args.role]
    if args.role == "admin":
        print("\nnote: 'admin' is the owner role in this schema.")

    name = args.name or args.email.split("@")[0]
    password = args.password or make_password()
    generated = args.password is None

    print(f"\ncreating {role}: {args.email}")

    status, body = api.login(args.email, password)
    if body.get("access_token"):
        print("  an account with this address and password already exists; "
              "leaving it alone")
        token = body["access_token"]
        uid = body["user"]["id"]
    else:
        status, body = api.call("/auth/v1/signup", {
            "email": args.email,
            "password": password,
            "data": {
                "role": role,
                "full_name": name,
                "firm_name": args.firm or name,
                "phone": args.phone,
                "city": args.city,
                "state": args.state,
            },
        })
        if status not in (200, 201):
            print(f"  signup failed: HTTP {status} {err_text(body)}")
            if status == 422 and "already" in err_text(body).lower():
                print("  the address is taken but that password does not open "
                      "it -- reset it in the Supabase dashboard instead.")
            return 1

        user = body.get("user") or body
        uid = user.get("id")
        confirmed = bool(user.get("email_confirmed_at") or user.get("confirmed_at"))
        print(f"  signed up: id={uid}  confirmed={confirmed}")
        if not confirmed:
            print("  not confirmed, so it cannot sign in yet. Stopping here "
                  "rather than reporting a login that will fail.")
            return 1

        status, body = api.login(args.email, password)
        token = body.get("access_token")
        if not token:
            print(f"  created, but sign-in failed: HTTP {status} {err_text(body)}")
            return 1

    # Optional fields handle_new_user() does not copy out of the metadata.
    patch = {k: v for k, v in (("gst_number", args.gst),
                               ("address", args.address)) if v}
    if patch:
        status, body = api.call(f"/rest/v1/profiles?id=eq.{uid}", patch,
                                token=token, method="PATCH")
        print(f"  profile extras: HTTP {status}"
              + (f" {err_text(body)}" if status >= 300 else " written"))

    # Filtered by id on purpose: an owner can read every profile, and an
    # unfiltered select would report whichever row came back first.
    status, rows = api.call(
        f"/rest/v1/profiles?select=role,status,full_name,firm_name,city&id=eq.{uid}",
        token=token)
    row = rows[0] if isinstance(rows, list) and rows else None
    if not row:
        print(f"  could not read the profile back: HTTP {status} {err_text(rows)}")
        return 1

    print("\nverified against the database:")
    for k, v in row.items():
        print(f"  {k:<12} {v}")

    print("\ncredentials")
    print(f"  email     {args.email}")
    print(f"  password  {password}" + ("  (generated)" if generated else ""))

    if row["role"] != role:
        print(f"\nWARNING: asked for {role}, the database made it {row['role']}.")
        print("This project's handle_new_user() trigger did not honour the "
              "metadata. Promote it in SQL:")
        print("  update public.profiles p set role = '%s', status = 'approved',"
              % role)
        print("         approved_at = now()")
        print("    from auth.users u")
        print(f"   where u.id = p.id and u.email = '{args.email}';")
        return 1

    if row["status"] != "approved":
        print(f"\nStatus is {row['status']}. A wholesaler is created pending by "
              "design and\nsees nothing in the catalogue until an owner "
              "approves it, from the\nowner app's dealer queue.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
