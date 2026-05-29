import axios from 'axios';

// Create a globally configured Axios instance
export const apiClient = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Interceptor to attach the API key + base URL to all requests.
// Credentials are shared with the rest of the app under a single key name
// (`ageval_key` / `ageval_url`) so connecting once works everywhere. The old
// `ageval_api_key` name is read as a fallback for in-flight sessions.
apiClient.interceptors.request.use((config) => {
  if (typeof window !== 'undefined') {
    const base =
      localStorage.getItem('ageval_url') || sessionStorage.getItem('ageval_url');
    if (base) {
      config.baseURL = base;
    }

    const token =
      localStorage.getItem('ageval_key') ||
      sessionStorage.getItem('ageval_key') ||
      localStorage.getItem('ageval_api_key'); // legacy fallback
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

export const jobsApi = {
  launchRedTeam: async (projectId: string) => {
    const response = await apiClient.post('/v1/jobs/redteam', {
      project_id: projectId,
      attack_vectors: ["prompt_injection", "data_exfiltration"]
    });
    return response.data;
  },
  
  getJobStatus: async (jobId: string) => {
    const response = await apiClient.get(`/v1/jobs/${jobId}`);
    return response.data;
  }
};

export const keysApi = {
  getKeys: async () => {
    const response = await apiClient.get('/keys');
    return response.data;
  },
  
  registerKey: async (label: string, adminSecret: string) => {
    const response = await apiClient.post('/register', { label }, {
      headers: {
        'x-admin-secret': adminSecret
      }
    });
    return response.data;
  },
  
  revokeKey: async (keyId: string) => {
    const response = await apiClient.delete(`/keys/${keyId}`);
    return response.data;
  }
};

