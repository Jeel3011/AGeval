export class ApiError extends Error {
  constructor(public message: string, public status?: number) {
    super(message);
  }
}

export function getConfig() {
  if (typeof window === 'undefined') return { key: '', base: '' };
  return {
    key: localStorage.getItem('ageval_key') || sessionStorage.getItem('ageval_key') || '',
    base: localStorage.getItem('ageval_url') || sessionStorage.getItem('ageval_url') || 'https://ageval-production.up.railway.app'
  };
}

export async function apiGet(path: string) {
  const { key, base } = getConfig();
  if (!key) throw new ApiError('No API key set. Click Settings to connect.');
  
  const res = await fetch(`${base}${path}`, {
    headers: { Authorization: `Bearer ${key}` }
  });
  
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(err.detail || `HTTP ${res.status}`, res.status);
  }
  return res.json();
}
