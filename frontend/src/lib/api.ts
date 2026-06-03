import { getSupabase, supabaseConfigured } from './supabase';

export class ApiError extends Error {
  constructor(public message: string, public status?: number) {
    super(message);
  }
}

/** Base URL of the AGeval backend. Defaults to local dev; overridable. */
export function getBaseUrl(): string {
  if (typeof window === 'undefined') return '';
  return (
    localStorage.getItem('ageval_url') ||
    process.env.NEXT_PUBLIC_API_URL ||
    'http://localhost:8000'
  );
}

/**
 * The bearer token for dashboard requests.
 *
 * Auth model: a human signs in with email/password (Supabase Auth) and the
 * dashboard authenticates with their Supabase JWT. Agents authenticate
 * separately with an `ageval-sk-…` API key issued from the dashboard. The
 * backend accepts either and resolves both to the same user_id.
 *
 * We prefer the live Supabase session token; we fall back to a manually stored
 * key (`ageval_key`) for power users / SDK debugging from the browser.
 */
async function getBearer(): Promise<string> {
  if (typeof window === 'undefined') return '';
  if (supabaseConfigured) {
    try {
      const { data } = await getSupabase().auth.getSession();
      const token = data.session?.access_token;
      if (token) return token;
    } catch {
      /* fall through to stored key */
    }
  }
  return localStorage.getItem('ageval_key') || sessionStorage.getItem('ageval_key') || '';
}

async function request(path: string, init?: RequestInit) {
  const base = getBaseUrl();
  const token = await getBearer();
  if (!token) throw new ApiError('Not signed in. Please sign in to continue.', 401);

  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      ...(init?.headers || {}),
      Authorization: `Bearer ${token}`,
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(err.detail || `HTTP ${res.status}`, res.status);
  }
  return res.json();
}

export async function apiGet(path: string) {
  return request(path);
}

export async function apiPost(path: string, body?: unknown) {
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export async function apiDelete(path: string) {
  return request(path, { method: 'DELETE' });
}
