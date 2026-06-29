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

// ----- R5-C Phase 4: 前端高级 Agent 面板契约 -----
// 仅在 enable_agent_workflow=True 时由后端 workflow preview 返回;
// 老路径 (enable_agent_workflow=False) 字节级一致不返这些字段。
// 前端展示只取摘要和计数, 不展示 text / jd / bullet 原文(隐私边界 spec §6.4)。

export interface AgentSummary {
  /** 短 uuid, "r" + 8 位 hex, 不含 PII / 时间戳 */
  request_id: string
  /** 任务图总步数(含本地步骤和工具步骤) */
  steps_executed: number
  /** 影响 preview 的有效工具(只列 affects_preview=True 且 status=success) */
  tools_used: string[]
  /** workflow 是否降级到旧路径 */
  fallback_used: boolean
  /** 降级原因(异常类型名 / 步骤名), fallback_used=False 时为 null */
  fallback_reason: string | null
  /** workflow 总耗时,毫秒 */
  latency_ms: number
}

export interface EvidenceSummary {
  /** 来源类型: "project" | "skill" | "honor" | "cert" */
  source_type: string
  /** 来源 id: project.id / skill group 名 / honor name / cert name */
  source_id: string
  /** 原文(text 字段前端不展示, 仅内部计算统计用, 防 PII 泄漏) */
  text: string
  /** 这条 evidence 里命中 JD 关键词的 normalized 列表(去重) */
  matched_keywords: string[]
  /** 置信度 [0.0, 1.0], round 3 位小数 */
  confidence: number
}

export interface ExternalResumePerspective {
  /** JD 要求 ∩ 简历里有 */
  have_keywords: string[]
  /** JD 要求 ∩ (简历里没 + 素材库也没) */
  need_keywords: string[]
  /** JD 要求 - 简历里有 ∩ 素材库能提供 */
  materials_can_cover: string[]
  /** 简历里有但 JD 没要求 */
  resume_only_keywords: string[]
  /** 补充建议, 1~N 条短句 */
  suggestions: string[]
  /** 4 维关键词计数 */
  counts: {
    have: number
    need: number
    materials_can_cover: number
    resume_only: number
  }
}

export interface BulletEvaluation {
  /** 项目 id (来自 materials.json projects[].id) */
  project_id: string
  /** 该项目 highlights 列表内索引 (0..N-1) */
  bullet_index: number
  /** 命中 JD 关键词 */
  matched_keywords: string[]
  /** 缺失 JD 关键词 */
  missing_keywords: string[]
  /** == len(matched_keywords) */
  matched_count: number
  /** == len(missing_keywords) */
  missing_count: number
  /** 1 句人话建议(spec §4.3) */
  suggestion: string
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
  // ----- R5-C Phase 4: Agent workflow 高级信息(可选, 仅 enable_agent_workflow=True 时存在) -----
  /** workflow 摘要: request_id / 步数 / 有效工具 / fallback / 耗时 */
  agent_summary?: AgentSummary
  /** 轻量 RAG evidence 摘要 dict list(前端只统计 source_type / confidence, 不展示 text) */
  evidence_summary?: EvidenceSummary[] | null
  /** 外部简历 have/need/gap 4 维摘要(无外部简历 / workflow 未跑时为 null) */
  external_resume_perspective?: ExternalResumePerspective | null
  /** per-bullet 真实评估摘要(前端只展示计数 + 建议, 不展示 bullet 原文) */
  bullet_evaluations?: BulletEvaluation[] | null
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
    // ----- R5-C Phase 4: Agent workflow 透传(后端默认 False 字节级一致) -----
    /** R5-A Phase 1: 启用 Agent workflow(默认 False, 老路径不返 agent_summary 等字段) */
    enable_agent_workflow?: boolean,
    /** R4-F: Function Calling 开关(默认 False, 走老改写路径) */
    enable_function_calling?: boolean,
    /** R4-M: 会话 id(同 session 累积 LLM 历史, 默认 None 不传) */
    session_id?: string | null,
    /** R5-C Phase 2: 外部简历全文(默认 None 不传; 仅 enable_agent_workflow=True 时有意义) */
    external_resume_text?: string | null,
  ) =>
    api
      .post<PreviewResponse>('/resume/preview', {
        target_role,
        intention,
        template,
        jd_text,
        academic_layout: academic_layout ?? null,
        enable_agent_workflow: enable_agent_workflow ?? false,
        enable_function_calling: enable_function_calling ?? false,
        session_id: session_id ?? null,
        external_resume_text: external_resume_text ?? null,
      })
      .then(r => r.data),
  generate: (
    target_role: string,
    intention?: string,
    template?: string,
    jd_text?: string | null,
    academic_layout?: 'compact' | 'detailed' | null,
    // ----- R5-C Phase 4: Agent workflow 透传(generate 路径仅前 3 个, external_resume 不传) -----
    enable_agent_workflow?: boolean,
    enable_function_calling?: boolean,
    session_id?: string | null,
  ) =>
    api
      .post(
        '/resume/generate',
        {
          target_role,
          intention,
          template,
          jd_text,
          academic_layout: academic_layout ?? null,
          enable_agent_workflow: enable_agent_workflow ?? false,
          enable_function_calling: enable_function_calling ?? false,
          session_id: session_id ?? null,
          // spec §5.2: generate 路径不默认传 external_resume_text
          // (字段在 PreviewRequest/GenerateRequest 已就位, 但前端不在 generate 调用)
        },
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

// ----- Round 6-A Phase 3: 面试官面板契约 -----
// 前端只消费自己新增的 5 个类型 + 4 个端点,不直接 import R5-C 的 workflow 诊断字段
// (AgentSummary / EvidenceSummary / ExternalResumePerspective / BulletEvaluation),
// 避免与现有 R5-C Phase 4 预览页诊断面板混淆(spec §3.3)。

export type InterviewState =
  | 'EMPTY'
  | 'DIAGNOSING'
  | 'ASKING'
  | 'DRAFT_READY'
  | 'SAVED'
  | 'ABORTED'

export type InterviewAction =
  | 'answer'
  | 'skip_question'
  | 'rephrase_question'
  | 'switch_gap'
  | 'draft_now'

export interface InterviewMessage {
  slot: string
  text: string
  quick_replies: string[]
}

export interface InterviewProgress {
  captured: Record<string, boolean>
  turn_count: number
  can_draft: boolean
}

export interface InterviewGap {
  gap_id: string
  label: string
  reason: string
  keywords: string[]
  tier: string
  priority: number
  suggested_slots: string[]
}

export interface InterviewDraftCard {
  title: string
  target_role?: string
  source_gap_id?: string
  background: string
  responsibility: string
  actions: string[]
  methods: string[]
  difficulty: string
  result: string
  metrics: string[]
  skills: string[]
  draft_bullets: string[]
  warnings: string[]
  summary?: string
}

export interface InterviewStartRequest {
  target_role: string
  jd_text: string
}

export interface InterviewStartResponse {
  session_id: string
  state: InterviewState
  selected_gap: InterviewGap
  message: InterviewMessage | null
  progress: InterviewProgress
}

export interface InterviewReplyRequest {
  session_id: string
  message: string
  action: InterviewAction
}

export interface InterviewReplyResponse {
  state: InterviewState
  message: InterviewMessage | null
  captured_delta: Record<string, unknown> | null
  progress: InterviewProgress
  can_draft: boolean
  force_draft: boolean
}

export interface InterviewDraftResponse {
  state: InterviewState
  draft_card: InterviewDraftCard
}

export interface InterviewSaveRequest {
  session_id: string
  edited_card: InterviewDraftCard
  save_mode: 'append_project'
}

export interface InterviewSaveResponse {
  ok: boolean
  material_ref: { type: 'project'; id: string }
  refresh: { should_refresh_preview: boolean; should_refresh_match: boolean }
  preview_score_delta: { before: number; after: number } | null
}

export const interviewApi = {
  start: (req: InterviewStartRequest) =>
    api.post<InterviewStartResponse>('/interview/start', req).then(r => r.data),
  reply: (req: InterviewReplyRequest) =>
    api.post<InterviewReplyResponse>('/interview/reply', req).then(r => r.data),
  draft: (session_id: string) =>
    api
      .post<InterviewDraftResponse>('/interview/draft', { session_id })
      .then(r => r.data),
  saveCard: (req: InterviewSaveRequest) =>
    api.post<InterviewSaveResponse>('/interview/save-card', req).then(r => r.data),
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