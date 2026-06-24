import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

export interface MaterialSummary {
  name: string
  school: string
  major: string
  project_count: number
  projects: { id: string; name: string; period: string }[]
  skill_groups: string[]
  honor_count: number
}

export interface Role {
  id: string
  name: string
  intention: string
  tone: string
}

export interface Section {
  type: string  // "header" | "education" | "project_group" | "skills" | "honors" | "self_eval"
  title: string
  content: any
}

export interface PreviewResponse {
  target_role: string
  intention: string
  sections: Section[]
}

export const materialsApi = {
  getSummary: () => api.get<MaterialSummary>('/materials/summary').then(r => r.data),
  getAll: () => api.get('/materials').then(r => r.data),
}

export const resumeApi = {
  listRoles: () => api.get<{ enabled: string[]; roles: Role[]; note: string }>('/resume/roles').then(r => r.data),
  preview: (target_role: string, intention?: string) =>
    api.post<PreviewResponse>('/resume/preview', { target_role, intention }).then(r => r.data),
  generate: (target_role: string, intention?: string) =>
    api
      .post('/resume/generate', { target_role, intention }, { responseType: 'blob' })
      .then(r => r.data as Blob),
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export default api
