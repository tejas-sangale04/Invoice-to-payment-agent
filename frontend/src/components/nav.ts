import {
  BarChart3,
  BookOpen,
  CheckSquare,
  FileText,
  Home,
  type LucideIcon,
  Settings2,
  ShoppingCart,
  Truck,
  Upload,
  Users,
} from 'lucide-react'

import type { Role } from '@/lib/api'

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  minimum?: Role
  end?: boolean
}

export const NAV: { section: string; items: NavItem[] }[] = [
  { section: '', items: [{ to: '/', label: 'Home', icon: Home, end: true }] },
  {
    section: 'Purchasing',
    items: [
      { to: '/purchase-orders', label: 'Purchase orders', icon: ShoppingCart, minimum: 'staff' },
      { to: '/deliveries/new', label: 'Record delivery', icon: Truck, minimum: 'staff' },
      { to: '/suppliers', label: 'Suppliers', icon: Users, minimum: 'staff' },
    ],
  },
  {
    section: 'Invoices',
    items: [
      { to: '/invoices/upload', label: 'Upload invoice', icon: Upload, minimum: 'staff' },
      { to: '/invoices', label: 'Invoices', icon: FileText, minimum: 'staff', end: true },
      { to: '/approvals', label: 'Approval queue', icon: CheckSquare, minimum: 'manager' },
    ],
  },
  {
    section: 'Finance',
    items: [
      { to: '/ledger', label: 'Ledger', icon: BookOpen, minimum: 'manager' },
      { to: '/dashboard', label: 'Dashboard', icon: BarChart3, minimum: 'manager' },
    ],
  },
  { section: 'Admin', items: [{ to: '/settings/rules', label: 'Business rules', icon: Settings2, minimum: 'admin' }] },
]
