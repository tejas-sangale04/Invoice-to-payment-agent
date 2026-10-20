"""Create one demo user per role (and a few demo suppliers) in the local Firebase emulators.

Run with the emulators started (`firebase emulators:start` from the repo root):

    export FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099 FIRESTORE_EMULATOR_HOST=127.0.0.1:8080
    python -m scripts.seed_emulator

Refuses to run against real Firebase, so it can never create users in production.
"""

import os
import sys

from fastapi import HTTPException
from firebase_admin import auth

from app.models.master_data import SupplierCreate
from app.services.firebase import init_firebase, set_role_claim
from app.services.firestore import get_db
from app.services.master_data import create_supplier

DEMO_PASSWORD = "password123"
DEMO_USERS = {
    "staff@invoiceflow.test": "staff",
    "manager@invoiceflow.test": "manager",
    "admin@invoiceflow.test": "admin",
}

DEMO_SUPPLIERS = [
    SupplierCreate(name="Sharma Dairy Pvt Ltd", email="accounts@sharmadairy.in"),
    SupplierCreate(name="Fresh Farms Produce", email="billing@freshfarms.in"),
    SupplierCreate(name="Metro Packaging Co", email="ar@metropack.in", gstin="27ABCDE1234F1Z5"),
]


def main() -> None:
    if not (
        os.environ.get("FIREBASE_AUTH_EMULATOR_HOST") and os.environ.get("FIRESTORE_EMULATOR_HOST")
    ):
        sys.exit("Emulator hosts are not set; refusing to touch real Firebase.")
    init_firebase()
    for email, role in DEMO_USERS.items():
        try:
            user = auth.get_user_by_email(email)
        except auth.UserNotFoundError:
            user = auth.create_user(email=email, password=DEMO_PASSWORD, display_name=role.title())
        set_role_claim(user.uid, role)
        print(f"{role:<8} {email} / {DEMO_PASSWORD}")

    db = get_db()
    for supplier in DEMO_SUPPLIERS:
        try:
            print("supplier", create_supplier(db, supplier).supplier_id, supplier.name)
        except HTTPException:
            print("supplier exists", supplier.name)


if __name__ == "__main__":
    main()
