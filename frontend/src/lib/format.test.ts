import { describe, expect, it } from 'vitest'

import { formatPaise, formatQty, lineAmounts, remainingQty, rupeesToPaise } from '@/lib/format'

describe('money helpers', () => {
  it('formats paise as Indian rupees', () => {
    expect(formatPaise(405000)).toBe('₹4,050.00')
    expect(formatPaise(123456789)).toBe('₹12,34,567.89')
  })

  it('parses rupee input without floating point', () => {
    expect(rupeesToPaise('60')).toBe(6000)
    expect(rupeesToPaise('60.5')).toBe(6050)
    expect(rupeesToPaise('0.07')).toBe(7)
    expect(rupeesToPaise('1.234')).toBeNull()
    expect(rupeesToPaise('-1')).toBeNull()
    expect(rupeesToPaise('')).toBeNull()
  })

  it('matches the backend line arithmetic', () => {
    // Same cases as backend/tests/test_money.py
    expect(lineAmounts('50', 6000, '0')).toEqual({ total: 300000, tax: 0 })
    expect(lineAmounts('1.5', 33, '18')).toEqual({ total: 50, tax: 9 })
    expect(lineAmounts('2.675', 10000, '5')).toEqual({ total: 26750, tax: 1338 })
    expect(lineAmounts('abc', 1, '0')).toBeNull()
  })

  it('formats and subtracts quantities', () => {
    expect(formatQty('2.500')).toBe('2.5')
    expect(formatQty('40')).toBe('40')
    expect(remainingQty('50', '40')).toBe('10')
    expect(remainingQty('2.5', '1.25')).toBe('1.25')
  })
})
