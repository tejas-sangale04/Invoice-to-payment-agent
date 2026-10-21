import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.master_data import GoodsReceiptCreate, PurchaseOrderCreate, SupplierCreate
from app.services.master_data import normalize_name
from tests.conftest import bearer


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("Sharma Dairy Pvt. Ltd.", "sharma dairy"),
        ("  SHARMA   dairy  ", "sharma dairy"),
        ("A&B Traders Private Limited", "a b traders"),
        ("Ltd", ""),
    ],
)
def test_normalize_name(raw: str, normalized: str) -> None:
    assert normalize_name(raw) == normalized


def test_gstin_is_validated_and_uppercased() -> None:
    s = SupplierCreate(name="X", email="a@b.com", gstin="27abcde1234f1z5")
    assert s.gstin == "27ABCDE1234F1Z5"
    assert SupplierCreate(name="X", email="a@b.com", gstin="").gstin is None
    with pytest.raises(ValidationError):
        SupplierCreate(name="X", email="a@b.com", gstin="NOT-A-GSTIN")


def test_po_needs_items_with_positive_qty_and_valid_tax() -> None:
    with pytest.raises(ValidationError):
        PurchaseOrderCreate(supplier_id="SUP-1", items=[])
    bad_lines = [
        {"name": "Milk", "qty": "0", "unit": "L", "unit_price_paise": 6000},
        {"name": "Milk", "qty": "1", "unit": "L", "unit_price_paise": -1},
        {"name": "Milk", "qty": "1", "unit": "L", "unit_price_paise": 6000, "tax_rate": "40"},
        {"name": " ", "qty": "1", "unit": "L", "unit_price_paise": 6000},
    ]
    for line in bad_lines:
        with pytest.raises(ValidationError):
            PurchaseOrderCreate(supplier_id="SUP-1", items=[line])


def test_receipt_rejects_zero_qty() -> None:
    with pytest.raises(ValidationError):
        GoodsReceiptCreate(
            po_number="PO-1",
            received_on="2026-10-20",
            items=[{"line_id": "1", "qty_received": "0"}],
        )


@pytest.mark.parametrize(
    ("method", "path", "token"),
    [
        ("post", "/suppliers", "staff-token"),
        ("post", "/suppliers", "manager-token"),
        ("get", "/business-rules", "manager-token"),
        ("put", "/business-rules", "manager-token"),
        ("get", "/suppliers", "norole-token"),
        ("post", "/purchase-orders", "norole-token"),
        ("post", "/goods-receipts", "norole-token"),
    ],
)
def test_role_checks(client: TestClient, method: str, path: str, token: str) -> None:
    res = getattr(client, method)(
        path, headers=bearer(token), **({} if method == "get" else {"json": {}})
    )
    assert res.status_code == 403


@pytest.mark.parametrize(
    "path", ["/suppliers", "/purchase-orders", "/goods-receipts", "/business-rules"]
)
def test_endpoints_need_a_token(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 401
