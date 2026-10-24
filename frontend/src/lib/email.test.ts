import { describe, expect, it } from 'vitest'

import { splitDraft } from '@/lib/email'

describe('splitDraft', () => {
  it('splits the subject line from the body', () => {
    const draft = 'Subject: Invoice SD-1\n\nDear Sharma Dairy,\n\nPlease send a credit note.\n\nAccounts Payable'
    expect(splitDraft(draft)).toEqual({
      subject: 'Invoice SD-1',
      body: 'Dear Sharma Dairy,\n\nPlease send a credit note.\n\nAccounts Payable',
    })
  })

  it('handles Windows line endings and a lower-case label', () => {
    expect(splitDraft('subject: Hello\r\n\r\nHi there')).toEqual({ subject: 'Hello', body: 'Hi there' })
  })

  it('keeps everything as the body when there is no subject line', () => {
    expect(splitDraft('Dear supplier,\nPlease reply.')).toEqual({ subject: '', body: 'Dear supplier,\nPlease reply.' })
  })

  it('copes with no draft', () => {
    expect(splitDraft(null)).toEqual({ subject: '', body: '' })
  })
})
