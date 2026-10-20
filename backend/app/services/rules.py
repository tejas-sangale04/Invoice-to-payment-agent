from google.cloud import firestore

from app.models.rules import BusinessRules


def _ref(db: firestore.Client) -> firestore.DocumentReference:
    return db.collection("business_rules").document("default")


def get_rules(db: firestore.Client) -> BusinessRules:
    snap = _ref(db).get()
    return BusinessRules(**snap.to_dict()) if snap.exists else BusinessRules()


def save_rules(db: firestore.Client, rules: BusinessRules) -> BusinessRules:
    _ref(db).set(rules.model_dump(mode="json"))
    return rules
