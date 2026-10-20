"""Create one demo user per role in the local Firebase Auth emulator.

Run with the emulators started (`firebase emulators:start` from the repo root):

    FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099 python -m scripts.seed_emulator_users

Refuses to run against real Firebase, so it can never create users in production.
"""

import os
import sys

from firebase_admin import auth

from app.services.firebase import init_firebase, set_role_claim

DEMO_PASSWORD = "password123"
DEMO_USERS = {
    "staff@invoiceflow.test": "staff",
    "manager@invoiceflow.test": "manager",
    "admin@invoiceflow.test": "admin",
}


def main() -> None:
    if not os.environ.get("FIREBASE_AUTH_EMULATOR_HOST"):
        sys.exit("FIREBASE_AUTH_EMULATOR_HOST is not set; refusing to touch real Firebase.")
    init_firebase()
    for email, role in DEMO_USERS.items():
        try:
            user = auth.get_user_by_email(email)
        except auth.UserNotFoundError:
            user = auth.create_user(email=email, password=DEMO_PASSWORD, display_name=role.title())
        set_role_claim(user.uid, role)
        print(f"{role:<8} {email} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
