"""Where invoice files live. Cloud Storage in production; a local folder for dev and tests.

Either way, the browser only ever gets a short-lived signed link to a file, never a public one.
"""

import datetime as dt
import hashlib
import hmac
import time
from functools import lru_cache
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode

from app.core.config import get_settings


class Storage(Protocol):
    def save(self, key: str, data: bytes, content_type: str) -> None: ...

    def read(self, key: str) -> bytes: ...

    def signed_url(self, key: str, content_type: str) -> str: ...


class LocalStorage:
    def __init__(self, root: str, base_url: str, secret: str, ttl: int) -> None:
        self.root = Path(root).resolve()
        self.base_url = base_url.rstrip("/")
        self.secret = secret.encode()
        self.ttl = ttl

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Invalid storage key")
        return path

    def save(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def _signature(self, key: str, content_type: str, expires: int) -> str:
        msg = f"{key}\n{content_type}\n{expires}".encode()
        return hmac.new(self.secret, msg, hashlib.sha256).hexdigest()

    def signed_url(self, key: str, content_type: str) -> str:
        expires = int(time.time()) + self.ttl
        query = urlencode(
            {
                "ct": content_type,
                "expires": expires,
                "sig": self._signature(key, content_type, expires),
            }
        )
        return f"{self.base_url}/files/{key}?{query}"

    def verify(self, key: str, content_type: str, expires: int, sig: str) -> bool:
        if expires < time.time():
            return False
        return hmac.compare_digest(sig, self._signature(key, content_type, expires))


class GcsStorage:
    def __init__(self, bucket: str, ttl: int) -> None:
        from google.cloud import storage

        self.bucket = storage.Client().bucket(bucket)
        self.ttl = ttl

    def save(self, key: str, data: bytes, content_type: str) -> None:
        self.bucket.blob(key).upload_from_string(data, content_type=content_type)

    def read(self, key: str) -> bytes:
        return self.bucket.blob(key).download_as_bytes()

    def signed_url(self, key: str, content_type: str) -> str:
        # On Cloud Run there is no private key file, so sign through the IAM API using the
        # service's own account (it needs roles/iam.serviceAccountTokenCreator on itself).
        import google.auth
        from google.auth.transport.requests import Request

        credentials, _ = google.auth.default()
        credentials.refresh(Request())
        return self.bucket.blob(key).generate_signed_url(
            version="v4",
            expiration=dt.timedelta(seconds=self.ttl),
            method="GET",
            response_type=content_type,
            service_account_email=credentials.service_account_email,
            access_token=credentials.token,
        )


@lru_cache
def get_storage() -> Storage:
    s = get_settings()
    if s.storage_mode == "gcs":
        return GcsStorage(s.gcs_bucket, s.file_url_ttl_seconds)
    return LocalStorage(
        s.local_storage_dir, s.api_base_url, s.file_url_secret, s.file_url_ttl_seconds
    )
