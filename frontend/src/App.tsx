import { Navigate, Route, Routes } from 'react-router-dom'

import { RequireAuth } from '@/auth/RequireAuth'
import { AppLayout } from '@/components/AppLayout'
import { BusinessRulesPage } from '@/pages/admin/BusinessRulesPage'
import { RecordDeliveryPage } from '@/pages/deliveries/RecordDeliveryPage'
import { HomePage } from '@/pages/HomePage'
import { InvoiceDetailPage } from '@/pages/invoices/InvoiceDetailPage'
import { InvoicesPage } from '@/pages/invoices/InvoicesPage'
import { UploadInvoicePage } from '@/pages/invoices/UploadInvoicePage'
import { LoginPage } from '@/pages/LoginPage'
import { ApprovalQueuePage } from '@/pages/manager/ApprovalQueuePage'
import { DashboardPage } from '@/pages/manager/DashboardPage'
import { LedgerPage } from '@/pages/manager/LedgerPage'
import { CreatePurchaseOrderPage } from '@/pages/purchase-orders/CreatePurchaseOrderPage'
import { PurchaseOrderDetailPage } from '@/pages/purchase-orders/PurchaseOrderDetailPage'
import { PurchaseOrdersPage } from '@/pages/purchase-orders/PurchaseOrdersPage'
import { SuppliersPage } from '@/pages/suppliers/SuppliersPage'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route index element={<HomePage />} />

        <Route path="purchase-orders" element={<RequireAuth minimum="staff"><PurchaseOrdersPage /></RequireAuth>} />
        <Route path="purchase-orders/new" element={<RequireAuth minimum="staff"><CreatePurchaseOrderPage /></RequireAuth>} />
        <Route path="purchase-orders/:poNumber" element={<RequireAuth minimum="staff"><PurchaseOrderDetailPage /></RequireAuth>} />
        <Route path="deliveries/new" element={<RequireAuth minimum="staff"><RecordDeliveryPage /></RequireAuth>} />
        <Route path="suppliers" element={<RequireAuth minimum="staff"><SuppliersPage /></RequireAuth>} />

        <Route path="invoices" element={<RequireAuth minimum="staff"><InvoicesPage /></RequireAuth>} />
        <Route path="invoices/upload" element={<RequireAuth minimum="staff"><UploadInvoicePage /></RequireAuth>} />
        <Route path="invoices/:invoiceId" element={<RequireAuth minimum="staff"><InvoiceDetailPage /></RequireAuth>} />

        <Route path="approvals" element={<RequireAuth minimum="manager"><ApprovalQueuePage /></RequireAuth>} />
        <Route path="ledger" element={<RequireAuth minimum="manager"><LedgerPage /></RequireAuth>} />
        <Route path="dashboard" element={<RequireAuth minimum="manager"><DashboardPage /></RequireAuth>} />

        <Route path="settings/rules" element={<RequireAuth minimum="admin"><BusinessRulesPage /></RequireAuth>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
