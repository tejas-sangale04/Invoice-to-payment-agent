/** A draft email as the Explanation Agent writes it: "Subject: …", a blank line, then the body. */
export function splitDraft(draft: string | null | undefined): { subject: string; body: string } {
  const text = (draft ?? '').replace(/\r\n/g, '\n').trim()
  const match = /^subject:[ \t]*(.*)\n?/i.exec(text)
  if (!match) return { subject: '', body: text }
  return { subject: match[1].trim(), body: text.slice(match[0].length).trim() }
}
