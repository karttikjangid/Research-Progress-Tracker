// Thin fetch helpers. Every non-2xx becomes a thrown Error with the server's detail.
async function handle(res) {
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`)
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
