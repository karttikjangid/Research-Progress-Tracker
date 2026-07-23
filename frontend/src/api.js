// Thin fetch helpers. Every non-2xx becomes a thrown Error with the server's
// detail; if the failure happened mid-way through processing a specific
// recording, the server also attaches X-Recording-Id (backend/main.py
// _process) so callers can recover that recording directly instead of
// guessing which one failed.
async function handle(res) {
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    const err = new Error(body.detail || `HTTP ${res.status}`)
    const rid = res.headers.get('X-Recording-Id')
    if (rid) err.recordingId = Number(rid)
    throw err
  }
  return body
}

export const get = (url) => fetch(url).then(handle)

export const post = (url, data) =>
  fetch(url, {
    method: 'POST',
    headers: data !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: data !== undefined ? JSON.stringify(data) : undefined,
  }).then(handle)

export const postForm = (url, formData) =>
  fetch(url, { method: 'POST', body: formData }).then(handle)
