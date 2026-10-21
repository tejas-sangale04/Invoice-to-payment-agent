from google.cloud import firestore


def next_id(
    transaction: firestore.Transaction, db: firestore.Client, name: str, prefix: str
) -> str:
    """Allocate the next sequential id (e.g. PO-1, PO-2) inside the caller's transaction."""
    ref = db.collection("counters").document(name)
    snap = ref.get(transaction=transaction)
    value = (snap.get("value") if snap.exists else 0) + 1
    transaction.set(ref, {"value": value})
    return f"{prefix}-{value}"
