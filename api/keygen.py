"""
api/keygen.py

Run this locally to create a new API key for a user.
Never run on the user's machine — this needs your Supabase service key.

Usage:
    python -m api.keygen --user you@example.com --label "first key"
"""

import argparse
import hashlib
import os
import secrets

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client


def generate_key() -> str:
    return "ageval-sk-" + secrets.token_hex(24)


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user",  required=True, help="user identifier (email or ID)")
    parser.add_argument("--label", default="",    help="human label for the key")
    args = parser.parse_args()

    client = create_client(
        os.environ["AGEVAL_SUPABASE_URL"],
        os.environ["AGEVAL_SUPABASE_SERVICE_KEY"],
    )

    raw_key  = generate_key()
    key_hash = hash_key(raw_key)

    client.table("api_keys").insert({
        "key_hash" : key_hash,
        "user_id"  : args.user,
        "label"    : args.label,
        "is_active": True,
    }).execute()

    print(f"\n✓ Key created for {args.user}")
    print(f"\n  AGEVAL_API_KEY={raw_key}\n")
    print("Give this to the user. It is NOT stored anywhere — if lost, create a new one.")


if __name__ == "__main__":
    main()
