import axios from 'axios';
import { getSupabase, supabaseConfigured } from './supabase';

// Create a globally configured Axios instance
export const apiClient = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Interceptor to attach the bearer token + base URL to all requests.
// Dashboard requests authenticate with the signed-in user's Supabase JWT;
// a manually stored `ageval_key` is the fallback. Base URL defaults to local
// dev unless overridden via `ageval_url`.
apiClient.interceptors.request.use(async (config) => {
  if (typeof window !== 'undefined') {
    const base = localStorage.getItem('ageval_url') || process.env.NEXT_PUBLIC_API_URL;
    if (base) {
      config.baseURL = base;
    }

    let token: string | null = null;
    if (supabaseConfigured) {
      try {
        const { data } = await getSupabase().auth.getSession();
        token = data.session?.access_token || null;
      } catch {
        /* fall through to stored key */
      }
    }
    if (!token) {
      token =
        localStorage.getItem('ageval_key') ||
        sessionStorage.getItem('ageval_key') ||
        localStorage.getItem('ageval_api_key'); // legacy fallback
    }
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

export interface Dataset {
  id: string;
  project_id: string;
  name: string;
  version: string;
  test_case_count: number;
  last_updated: string;
}

export const datasetsApi = {
  getDatasets: async (projectId: string): Promise<Dataset[]> => {
    const response = await apiClient.get(`/v1/datasets?project_id=${projectId}`);
    return response.data;
  },
  
  createDataset: async (data: any): Promise<Dataset> => {
    const response = await apiClient.post('/v1/datasets', data);
    return response.data;
  }
};

export interface RedTeamScorecard {
  model: string;
  probes_run: number;
  bypasses: number;
  overall_grade: string;
  overall_bypass_rate: number;
  prompt_injection_bypass_rate: number;
  roleplay_jailbreak_bypass_rate: number;
  data_exfiltration_bypass_rate: number;
  dow_success_rate: number;
  results: Array<{
    vector: string;
    name: string;
    severity: string;
    bypassed: boolean;
    response_preview: string;
  }>;
}

export const redTeamApi = {
  // Synchronous: runs the probe library against the model and returns a REAL
  // scorecard from the model's actual responses (no fake progress polling).
  run: async (agentId: string, model = 'gpt-4o-mini'): Promise<{ scorecard: RedTeamScorecard }> => {
    const response = await apiClient.post('/redteam/run', {
      agent_id: agentId,
      model,
      attack_vectors: ['prompt_injection', 'roleplay_jailbreak', 'data_exfiltration', 'dow'],
    });
    return response.data;
  },
};

export const keysApi = {
  getKeys: async () => {
    const response = await apiClient.get('/keys');
    return response.data;
  },

  // Issue a new agent API key for the signed-in user (session-gated; no admin
  // secret). The raw key is returned once.
  createKey: async (label: string) => {
    const response = await apiClient.post('/keys', { label });
    return response.data;
  },

  revokeKey: async (keyId: string) => {
    const response = await apiClient.delete(`/keys/${keyId}`);
    return response.data;
  }
};

