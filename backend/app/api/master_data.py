from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import Cursor, Db, Limit
from app.models.common import Page
from app.models.master_data import (
    GoodsReceipt,
    GoodsReceiptCreate,
    POStatus,
    PurchaseOrder,
    PurchaseOrderCreate,
    Supplier,
    SupplierCreate,
)
from app.models.user import CurrentUser, Role
from app.services import master_data as svc
from app.services.auth import require_role

router = APIRouter()

Staff = Depends(require_role(Role.staff))
Admin = Depends(require_role(Role.admin))


@router.post("/suppliers", response_model=Supplier, status_code=201, tags=["suppliers"])
def create_supplier(body: SupplierCreate, db: Db, _: CurrentUser = Admin) -> Supplier:
    return svc.create_supplier(db, body)


@router.get("/suppliers", response_model=Page[Supplier], tags=["suppliers"])
def list_suppliers(
    db: Db, limit: Limit = 50, cursor: Cursor = None, _: CurrentUser = Staff
) -> Page[Supplier]:
    return svc.list_suppliers(db, limit, cursor)


@router.post(
    "/purchase-orders", response_model=PurchaseOrder, status_code=201, tags=["purchase orders"]
)
def create_purchase_order(
    body: PurchaseOrderCreate, db: Db, user: CurrentUser = Staff
) -> PurchaseOrder:
    return svc.create_purchase_order(db, body, created_by=user.uid)


@router.get("/purchase-orders", response_model=Page[PurchaseOrder], tags=["purchase orders"])
def list_purchase_orders(
    db: Db,
    status: POStatus | None = None,
    limit: Limit = 50,
    cursor: Cursor = None,
    _: CurrentUser = Staff,
) -> Page[PurchaseOrder]:
    return svc.list_purchase_orders(db, limit, cursor, status)


@router.get("/purchase-orders/{po_number}", response_model=PurchaseOrder, tags=["purchase orders"])
def get_purchase_order(po_number: str, db: Db, _: CurrentUser = Staff) -> PurchaseOrder:
    po = svc.get_purchase_order(db, po_number)
    if po is None:
        raise HTTPException(status_code=404, detail=f"{po_number} not found")
    return po


@router.post(
    "/goods-receipts", response_model=GoodsReceipt, status_code=201, tags=["goods receipts"]
)
def create_goods_receipt(
    body: GoodsReceiptCreate, db: Db, user: CurrentUser = Staff
) -> GoodsReceipt:
    return svc.create_goods_receipt(db, body, received_by=user.uid)


@router.get("/goods-receipts", response_model=Page[GoodsReceipt], tags=["goods receipts"])
def list_goods_receipts(
    db: Db,
    po_number: str | None = None,
    limit: Limit = 50,
    cursor: Cursor = None,
    _: CurrentUser = Staff,
) -> Page[GoodsReceipt]:
    return svc.list_goods_receipts(db, limit, cursor, po_number)
