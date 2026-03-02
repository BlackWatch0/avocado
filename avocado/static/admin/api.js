const parseError = async (res, fallback) => {
  const text = await res.text();
  return new Error(`${fallback}: ${res.status} ${text}`);
};

export const apiGetJson = async (url, fallback) => {
  const res = await fetch(url);
  if (!res.ok) throw await parseError(res, fallback);
  return res.json();
};

export const apiPost = async (url, fallback, payload = null) => {
  const options = { method: "POST" };
  if (payload !== null) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(payload);
  }
  const res = await fetch(url, options);
  if (!res.ok) throw await parseError(res, fallback);
  return res.json().catch(() => ({}));
};

export const apiPut = async (url, fallback, payload) => {
  const res = await fetch(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw await parseError(res, fallback);
  return res.json();
};
