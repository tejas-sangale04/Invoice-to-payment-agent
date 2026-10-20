from fastapi import HTTPException
from google.cloud import firestore


def paginate(
    query: firestore.Query,
    collection: firestore.CollectionReference,
    limit: int,
    cursor: str | None,
    order_field: str = "created_at",
) -> tuple[list[firestore.DocumentSnapshot], str | None]:
    """Newest first. The cursor is the id of the last document on the previous page."""
    query = query.order_by(order_field, direction=firestore.Query.DESCENDING)
    if cursor:
        start = collection.document(cursor).get()
        if not start.exists:
            raise HTTPException(status_code=400, detail="Invalid cursor")
        query = query.start_after(start)
    docs = list(query.limit(limit + 1).stream())
    has_more = len(docs) > limit
    docs = docs[:limit]
    return docs, (docs[-1].id if has_more else None)
