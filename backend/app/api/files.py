"""Serves invoice files for local dev through signed, expiring links (production uses
Cloud Storage signed URLs instead, and this route returns 404)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from app.services.storage import LocalStorage, Storage, get_storage

router = APIRouter(include_in_schema=False)


@router.get("/files/{key:path}")
def get_file(
    key: str, ct: str, expires: int, sig: str, storage: Annotated[Storage, Depends(get_storage)]
) -> Response:
    if not isinstance(storage, LocalStorage):
        raise HTTPException(status_code=404, detail="Not found")
    if not storage.verify(key, ct, expires, sig):
        raise HTTPException(status_code=403, detail="This file link is invalid or has expired")
    try:
        data = storage.read(key)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    return Response(
        content=data,
        media_type=ct,
        headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"},
    )
