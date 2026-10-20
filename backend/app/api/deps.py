from typing import Annotated

from fastapi import Depends, Query
from google.cloud import firestore

from app.services.firestore import get_db

Db = Annotated[firestore.Client, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(description="next_cursor from the previous page")]
