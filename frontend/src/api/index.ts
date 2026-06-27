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

// ----- Round 3 J: 5 套排版模板 -----
export interface Template {
  id: string
  name: string
  description: string
}

export interface Section {
  type: string  // "header" | "education" | "project_group" | "skills" | "honors" | "self_eval"
  title: string
  content: any
}

export interface PreviewResponse {
  target_role: string
  template: string  // Round 3 J
  // R3-M.3: academic 模板时透传 compact / detailed;其他模板 null
  academic_layout: 'compact' | 'detailed' | null
  intention: string
  sections: Section[]
  // Round 3 I: 各 section / 各 project / 各 skill group 的 JD 命中关键词数
  // (None = 未传 JD,前端不显示角标)
  jd_match_counts: { projects: number[]; skill_groups: number[] } | null
}

// ----- Round 2 #2: JD 解析 + 匹配度评分 -----
export interface JdParseResult {
  skills: string[]
  tools: string[]
  domains: string[]
  experience_years: string
  education: string
  raw_keywords: string[]
  // ----- Round 3 A: tier 关键词分组 -----
  tier_info: { required: string[]; preferred: string[]; bonus: string[] }
}

export interface ResumePerspective {
  // R3-G 新增: 简历视角 (上传简历后才有, None 时 match 响应不返回)
  have_keywords: string[]   // JD 要求 ∩ 简历里有
  need_keywords: string[]   // JD 要求 - 简历里有 - 素材库能提供
  have_count: number
  need_count: number
}

export interface JdMatchResult {
  score: number
  matched_keywords: string[]
  missing_keywords: string[]
  coverage: { skills: number; tools: number; domains: number }
  suggestions: string[]
  role_id: string
  // ----- Round 3 A: tier 透传 + 业务阈值建议 -----
  tier_info: { required: string[]; preferred: string[]; bonus: string[] }
  recommendation: '高' | '中' | '低'
  // ----- R3-G: 简历视角 (外部简历全文非空时存在) -----
  resume_perspective: ResumePerspective | null
}

// ----- R3-G: 外部简历解析 -----
export interface ParsedParagraph {
  idx: number
  text: string
  is_heading: boolean
  page?: number
}

export interface ParsedResume {
  filename: string
  size_bytes: number
  paragraphs: ParsedParagraph[]
  page_count?: number
  note?: string
}

export const materialsApi = {
  getSummary: () => api.get<MaterialSummary>('/materials/summary').then(r => r.data),
  getAll: () => api.get('/materials').then(r => r.data),
}

export const resumeApi = {
  listRoles: () =>
    api
      .get<{ enabled: string[]; roles: Role[]; templates: Template[]; note: string }>(
        '/resume/roles'
      )
      .then(r => r.data),
  preview: (
    target_role: string,
    intention?: string,
    template?: string,
    jd_text?: string | null,
    // R3-M.3: academic 模板 detailed/compact 切换;其他模板传 null/undefined
    academic_layout?: 'compact' | 'detailed' | null,
  ) =>
    api
      .post<PreviewResponse>('/resume/preview', {
        target_role,
        intention,
        template,
        jd_text,
        academic_layout: academic_layout ?? null,
      })
      .then(r => r.data),
  generate: (
    target_role: string,
    intention?: string,
    template?: string,
    jd_text?: string | null,
    academic_layout?: 'compact' | 'detailed' | null,
  ) =>
    api
      .post(
        '/resume/generate',
        { target_role, intention, template, jd_text, academic_layout: academic_layout ?? null },
        { responseType: 'blob' },
      )
      .then(r => r.data as Blob),
  // R3-G 新增: 解析外部简历 (.docx/.pdf/.txt)
  parseExternal: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api
      .post<ParsedResume>('/resume/parse-external', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then(r => r.data)
  },
}

// ----- Round 2 #2: JD API -----
export const jdApi = {
  parse: (text: string) =>
    api.post<JdParseResult>('/jd/parse', { text }).then(r => r.data),
  // R3-G 改: external_resume_text 可选 (上传简历的全文, 触发简历视角)
  match: (text: string, target_role: string, external_resume_text?: string | null) =>
    api
      .post<JdMatchResult>('/jd/match', { text, target_role, external_resume_text: external_resume_text || null })
      .then(r => r.data),
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