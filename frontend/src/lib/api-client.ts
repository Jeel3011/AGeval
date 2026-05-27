import axios from 'axios';

// Create a globally configured Axios instance
export const apiClient = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Interceptor to attach the API Key to all requests
apiClient.interceptors.request.use((config) => {
  // In a real app, this would be fetched from secure storage or NextAuth session
  const token = localStorage.getItem('ageval_api_key') || 'ageval-sk-demo';
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
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

