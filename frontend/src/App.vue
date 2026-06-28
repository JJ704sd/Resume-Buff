<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  materialsApi,
  resumeApi,
  jdApi,
  downloadBlob,
  type MaterialSummary,
  type Role,
  type Template,
  type PreviewResponse,
  type JdMatchResult,
  type Section,
  type EvidenceSummary,
  type BulletEvaluation,
} from './api'
import ResumeUploader from './components/ResumeUploader.vue'  // R3-G

const summary = ref<MaterialSummary | null>(null)
const roles = ref<Role[]>([])
const enabledRoles = ref<string[]>([])

// Round 3 J: 模板库
const templates = ref<Template[]>([])

// 表单
const selectedRole = ref<string>('tech_metric')
const selectedTemplate = ref<string>('classic')
const customIntention = ref<string>('')

// R3-M.3: academic 模板二级选项(compact 紧凑版 / detailed 详细版)
// 仅在 selectedTemplate === 'academic' 时透传给后端,其他模板忽略
const academicLayout = ref<'compact' | 'detailed'>('compact')

// R3-M.3: bilingual 模板 tooltip — 提示用户补双语字段可以解锁完整双语渲染
const bilingualTooltip =
  '如需完整双语 header / 教育 / 项目副标题,请在 materials.json 中补充 ' +
  'basics.name_en / education.school_en / education.major_en / projects[].title_en 字段。' +
  '字段缺失时自动降级为单语言。'

// Round 2 #2: JD 解析 + 匹配度评分
const jdText = ref<string>('')
const jdLoading = ref(false)
const jdResult = ref<JdMatchResult | null>(null)

// R3-G: 外部简历全文 (从 ResumeUploader 组件 emit 填入)
const externalResumeText = ref<string>('')
const externalResumeFilename = ref<string>('')

// Round 3 I: 按 JD 智能排序(checkbox) — 默认 unchecked,unchecked 时不传 jd_text
const jdAware = ref(false)
// 角标总开关(预览页"命中 N 关键词"chip) — 默认开
const jdAwareBadgeEnabled = ref(true)

// Round 2 #3: LLM 改写 toggle (UI 提示,实际启用需后端 LLM_API_KEY)
const llmHintShown = ref(true)

// ----- R5-C Phase 4: Agent workflow 高级面板 -----
// 默认关。开启时:
//   - preview() 多传 enable_agent_workflow=true
//   - previewData 上出现 agent_summary / evidence_summary /
//     external_resume_perspective / bullet_evaluations 字段
//   - 预览页头部出现默认收起的"Agent Workflow 诊断"面板
//   - 不开启时整个面板不渲染,与原 UI 字节级一致(spec §5.4 验收)
const enableAgentWorkflow = ref(false)
// 前端生成的 session_id(不存 PII,纯随机 uuid4); 默认空 = 后端按 None 处理
// 仅在 enable_agent_workflow=true 时后端才会真正用(否则字段透传但不影响主流程)
const agentSessionId = ref<string>('')
// el-collapse v-model — 空数组 = 全部收起
const agentPanelActive = ref<string[]>([])

function generateAgentSessionId(): string {
  // crypto.randomUUID() 浏览器原生,无依赖。失败时退到 Math.random 兜底。
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID()
    }
  } catch {
    /* fallthrough */
  }
  return 's-' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36)
}

// 勾上 enableAgentWorkflow 时 lazy 生成一次 session_id(后续同会话复用)
function ensureAgentSessionId(): string {
  if (!agentSessionId.value) {
    agentSessionId.value = generateAgentSessionId()
  }
  return agentSessionId.value
}

// 流程
type Stage = 'select' | 'preview' | 'done'
const stage = ref<Stage>('select')
const loading = ref(false)
const previewData = ref<PreviewResponse | null>(null)
const lastDownloaded = ref<{ name: string; size: number; time: string } | null>(null)

// 默认展开的项目(最关键的两块)
const defaultActive = ref<string[]>(['education', 'project_group', 'skills'])

onMounted(async () => {
  try {
    const [s, r] = await Promise.all([materialsApi.getSummary(), resumeApi.listRoles()])
    summary.value = s
    roles.value = r.roles
    enabledRoles.value = r.enabled
    templates.value = r.templates ?? []
    if (r.roles.length > 0) selectedRole.value = r.roles[0].id
  } catch (e) {
    ElMessage.error('加载失败:请确认后端已启动 (python backend/main.py)')
    console.error(e)
  }
})

const currentRole = computed(() => roles.value.find(r => r.id === selectedRole.value))

// ---------- 阶段 1: 选岗位 → 预览 ----------
async function onPreview() {
  if (!selectedRole.value) {
    ElMessage.warning('请先选择目标岗位')
    return
  }
  // Round 3 I: 勾上 jdAware 时要求 jdText 非空
  if (jdAware.value && !jdText.value.trim()) {
    ElMessage.warning('勾选「按 JD 智能排序」需要先在下方粘贴 JD 文本')
    return
  }
  loading.value = true
  try {
    const jdForBackend = jdAware.value ? jdText.value.trim() : null
    // R3-M.3: 仅 academic 模板透传 academic_layout,其他模板传 null(后端忽略)
    const layoutForBackend =
      selectedTemplate.value === 'academic' ? academicLayout.value : null
    // R5-C Phase 4: Agent workflow 透传。enableAgentWorkflow=false 时,
    // 后端走老路径字节级一致(spec §5.4 验收 — UI 不变)。
    const enableAgent = enableAgentWorkflow.value
    const sessionId = enableAgent ? ensureAgentSessionId() : null
    const extResume = enableAgent && externalResumeText.value.trim()
      ? externalResumeText.value.trim()
      : null
    previewData.value = await resumeApi.preview(
      selectedRole.value,
      customIntention.value.trim() || undefined,
      selectedTemplate.value,
      jdForBackend,
      layoutForBackend,
      enableAgent,
      false,                       // enable_function_calling: 默认 False,保持旧路径
      sessionId,
      extResume,
    )
    stage.value = 'preview'
    // 新一轮 preview 时,默认收起 Agent 面板,避免上一次展开状态残留
    agentPanelActive.value = []
    ElMessage.success('预览已生成,请 review 每个模块内容')
  } catch (e: any) {
    ElMessage.error(`预览失败: ${e?.response?.data?.detail ?? e?.message ?? '未知错误'}`)
  } finally {
    loading.value = false
  }
}

// ---------- Round 2 #2: JD 解析 + 匹配度评分 ----------
async function onScoreJd() {
  const text = jdText.value.trim()
  if (!text) {
    ElMessage.warning('请粘贴 JD 文本')
    return
  }
  if (!selectedRole.value) {
    ElMessage.warning('请先选择目标岗位')
    return
  }
  jdLoading.value = true
  try {
    // R3-G: 透传 external_resume_text (上传简历后才有)
    jdResult.value = await jdApi.match(
      text,
      selectedRole.value,
      externalResumeText.value.trim() || null,
    )
  } catch (e: any) {
    ElMessage.error(`评分失败: ${e?.response?.data?.detail ?? e?.message ?? '未知错误'}`)
    jdResult.value = null
  } finally {
    jdLoading.value = false
  }
}

// R3-G: 处理 ResumeUploader emit('parsed') 事件
function onResumeParsed(payload: {
  filename: string
  text: string
  paragraphs: any[]
}) {
  externalResumeFilename.value = payload.filename
  externalResumeText.value = payload.text
  ElMessage.success(
    `已上传简历: ${payload.filename} (${payload.paragraphs.length} 段, ${payload.text.length} 字符)`,
  )
}

// R3-G: 清除已上传简历
function onClearResume() {
  externalResumeFilename.value = ''
  externalResumeText.value = ''
}

// 分数 → 颜色 (高/中/低)
// 阈值与后端 _classify_recommendation (80/60) 保持一致 — 否则 score=50-59 时
// el-alert banner 显示红色"需大幅补充" + score-tag 显示橙色"建议补充",文案冲突
function scoreColor(s: number): string {
  if (s >= 80) return '#67c23a'  // green
  if (s >= 60) return '#e6a23c'  // orange
  return '#f56c6c'                // red
}
function scoreTag(s: number): 'success' | 'warning' | 'danger' {
  if (s >= 80) return 'success'
  if (s >= 60) return 'warning'
  return 'danger'
}

// Round 3 A: recommendation → el-alert type + 文案
function recommendationAlertType(
  r: '高' | '中' | '低' | undefined,
): 'success' | 'warning' | 'error' {
  if (r === '高') return 'success'
  if (r === '中') return 'warning'
  return 'error'
}
function recommendationAlertTitle(r: '高' | '中' | '低' | undefined): string {
  if (r === '高') return '强烈推荐投递'
  if (r === '中') return '建议补充素材后再投递'
  return '需大幅补充素材'
}
function recommendationAlertDetail(r: '高' | '中' | '低' | undefined): string {
  if (r === '高') return '关键词覆盖完整，可立即行动'
  if (r === '中') return '部分关键词尚可加强，补充后再投递命中率更高'
  return '当前覆盖与岗位要求差距较大，建议先扩充素材库'
}

function backToSelect() {
  stage.value = 'select'
  previewData.value = null
}

// ---------- 阶段 2: 确认下载 ----------
async function onConfirmDownload() {
  if (!previewData.value) return

  // 二次确认(防误操作)
  try {
    await ElMessageBox.confirm(
      '即将把上述预览内容写入 .docx,确认无误后开始生成?',
      '最终确认',
      { confirmButtonText: '确认下载', cancelButtonText: '再检查一下', type: 'info' }
    )
  } catch {
    return  // 用户点了取消
  }

  loading.value = true
  try {
    const jdForBackend = jdAware.value ? jdText.value.trim() : null
    // R3-M.3: 仅 academic 模板透传 academic_layout
    const layoutForBackend =
      selectedTemplate.value === 'academic' ? academicLayout.value : null
    // R5-C Phase 4: generate 路径透传 enable_agent_workflow + session_id,
    // 跟 preview 保持一致(spec §5.2: generate 不传 external_resume_text)。
    const enableAgent = enableAgentWorkflow.value
    const sessionId = enableAgent && agentSessionId.value ? agentSessionId.value : null
    const blob = await resumeApi.generate(
      selectedRole.value,
      customIntention.value.trim() || undefined,
      selectedTemplate.value,
      jdForBackend,
      layoutForBackend,
      enableAgent,
      false,    // enable_function_calling: 默认 False
      sessionId,
    )
    const roleName = currentRole.value?.name ?? '简历'
    const filename = `${summary.value?.name ?? '简历'}_${roleName}_${new Date().toISOString().slice(0, 10)}.docx`
    downloadBlob(blob, filename)
    lastDownloaded.value = {
      name: filename,
      size: blob.size,
      time: new Date().toLocaleString('zh-CN'),
    }
    stage.value = 'done'
    ElMessage.success('已生成并下载到本地')
  } catch (e: any) {
    ElMessage.error(`生成失败: ${e?.response?.data?.detail ?? e?.message ?? '未知错误'}`)
  } finally {
    loading.value = false
  }
}

function startOver() {
  stage.value = 'select'
  previewData.value = null
  lastDownloaded.value = null
}

function formatSize(b: number) {
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`
  return `${(b / 1024 / 1024).toFixed(2)} MB`
}

// 渲染辅助
function isProjectGroup(s: Section) { return s.type === 'project_group' }
function isHeader(s: Section) { return s.type === 'header' }
function isSkills(s: Section) { return s.type === 'skills' }
function isList(s: Section) { return s.type === 'honors' || s.type === 'self_eval' }

// Round 3 I: 角标辅助 — 仅在 jdAware + BadgeEnabled + 后端真返回 jd_match_counts 时显示
function showProjectBadge(projectIndex: number): boolean {
  if (!jdAware.value || !jdAwareBadgeEnabled.value) return false
  const counts = previewData.value?.jd_match_counts
  if (!counts) return false
  return projectIndex >= 0 && projectIndex < counts.projects.length
}
function showSkillBadge(groupIndex: number): boolean {
  if (!jdAware.value || !jdAwareBadgeEnabled.value) return false
  const counts = previewData.value?.jd_match_counts
  if (!counts) return false
  return groupIndex >= 0 && groupIndex < counts.skill_groups.length
}
function projectMatchCount(projectIndex: number): number {
  return previewData.value?.jd_match_counts?.projects[projectIndex] ?? 0
}
function skillMatchCount(groupIndex: number): number {
  return previewData.value?.jd_match_counts?.skill_groups[groupIndex] ?? 0
}

// ---------- R5-C Phase 4: Agent 面板辅助 (computed + helpers) ----------
// 隐私边界: 仅展示摘要 / 计数 / 关键词标签 / 短建议; 不展示 evidence.text /
// bullet 原文 / JD 原文 / 简历原文 / 真实姓名手机邮箱(spec §6.4)

/** 预览页是否应渲染 Agent 面板 — 仅在 enable_agent_workflow=true 且后端真返回 agent_summary 时 */
const hasAgentPanel = computed(() => Boolean(previewData.value?.agent_summary))

/** evidence_summary 是否非空(用于折叠面板内的子节) */
const evidenceList = computed<EvidenceSummary[]>(() => {
  const es = previewData.value?.evidence_summary
  return Array.isArray(es) ? es : []
})
const hasEvidence = computed(() => evidenceList.value.length > 0)

/** bullet_evaluations 是否非空 */
const bulletList = computed<BulletEvaluation[]>(() => {
  const be = previewData.value?.bullet_evaluations
  return Array.isArray(be) ? be : []
})
const hasBulletEvaluations = computed(() => bulletList.value.length > 0)

/** 外部简历 perspective 是否存在且非空(无外部简历时为 null,前端不渲染) */
const extPerspective = computed(() => previewData.value?.external_resume_perspective ?? null)
const hasExtPerspective = computed(() =>
  Boolean(extPerspective.value) && Boolean(extPerspective.value?.counts),
)

// evidence 来源分桶统计(spec §5.3 panel 要求 "来源类型统计, 不展示完整 evidence text")
interface EvidenceStats {
  bySource: { project: number; skill: number; honor: number; cert: number }
  total: number
  maxConfidence: number
  avgConfidence: number
  totalMatchedKw: number  // 所有 evidence.matched_keywords 去重后求和(等价总和)
}
const evidenceStats = computed<EvidenceStats>(() => {
  const list = evidenceList.value
  const bySource = { project: 0, skill: 0, honor: 0, cert: 0 }
  let maxC = 0
  let sumC = 0
  let totalKw = 0
  for (const ev of list) {
    const t = ev.source_type
    if (t === 'project') bySource.project++
    else if (t === 'skill') bySource.skill++
    else if (t === 'honor') bySource.honor++
    else if (t === 'cert') bySource.cert++
    if (ev.confidence > maxC) maxC = ev.confidence
    sumC += ev.confidence
    totalKw += Array.isArray(ev.matched_keywords) ? ev.matched_keywords.length : 0
  }
  const total = list.length
  return {
    bySource,
    total,
    maxConfidence: maxC,
    avgConfidence: total > 0 ? sumC / total : 0,
    totalMatchedKw: totalKw,
  }
})

// bullet 评估聚合摘要(spec §4.3 / §5.3 — 不展示 bullet 原文)
interface ProjectBulletStat {
  project_id: string
  total: number
  matched: number
  missing: number
  /** 该项目 top-1 suggestion(其他在面板里另列) */
  topSuggestion: string
}
interface BulletStats {
  total: number
  totalMatched: number
  totalMissing: number
  /** 按 project_id 分组(只在调用方用到 N 个项目时填充) */
  byProject: ProjectBulletStat[]
  /** 全局 top 建议(最多 3 条, 非空 suggestion 优先) */
  topSuggestions: string[]
}
const bulletStats = computed<BulletStats>(() => {
  const list = bulletList.value
  let totalMatched = 0
  let totalMissing = 0
  const projMap = new Map<string, ProjectBulletStat>()
  const suggestions: string[] = []
  for (const b of list) {
    totalMatched += b.matched_count
    totalMissing += b.missing_count
    const pid = b.project_id || '(unknown)'
    let s = projMap.get(pid)
    if (!s) {
      s = { project_id: pid, total: 0, matched: 0, missing: 0, topSuggestion: '' }
      projMap.set(pid, s)
    }
    s.total++
    s.matched += b.matched_count
    s.missing += b.missing_count
    if (!s.topSuggestion && b.suggestion) s.topSuggestion = b.suggestion
    if (b.suggestion) suggestions.push(b.suggestion)
  }
  return {
    total: list.length,
    totalMatched,
    totalMissing,
    byProject: Array.from(projMap.values()),
    topSuggestions: suggestions.slice(0, 3),
  }
})

/** fallback 文案(给面板展示用,不暴露底层异常 message) */
function fallbackText(): string {
  const s = previewData.value?.agent_summary
  if (!s) return ''
  if (!s.fallback_used) return '正常 (无 fallback)'
  const reason = s.fallback_reason ? ` · 原因: ${s.fallback_reason}` : ''
  return `降级${reason}`
}

/** 复制 request_id 到剪贴板 */
async function copyRequestId() {
  const rid = previewData.value?.agent_summary?.request_id
  if (!rid) return
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(rid)
      ElMessage.success(`已复制 request_id: ${rid}`)
      return
    }
  } catch {
    /* fallthrough */
  }
  // 旧浏览器降级
  const ta = document.createElement('textarea')
  ta.value = rid
  ta.style.position = 'fixed'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.select()
  try {
    document.execCommand('copy')
    ElMessage.success(`已复制 request_id: ${rid}`)
  } catch {
    ElMessage.warning('复制失败,请手动选中')
  } finally {
    document.body.removeChild(ta)
  }
}

/** 当前 agent workflow 的工具调用列表(有效工具,只列 affects_preview=True 且 success) */
const agentToolsUsed = computed(() => previewData.value?.agent_summary?.tools_used ?? [])
</script>

<template>
  <div class="layout">
    <header class="topbar">
      <div class="brand">
        <span class="logo">JLB</span>
        <div class="title-block">
          <h1>简历帮</h1>
          <p class="subtitle">一份素材库 · 一键生成多份针对性简历</p>
        </div>
      </div>
      <div class="stage-indicator">
        <el-steps :active="stage === 'select' ? 0 : stage === 'preview' ? 1 : 2" finish-status="success" simple>
          <el-step title="选择" />
          <el-step title="预览" />
          <el-step title="下载" />
        </el-steps>
      </div>
    </header>

    <main class="main">
      <!-- ============ 阶段 1: 选择岗位 ============ -->
      <template v-if="stage === 'select'">
        <el-row :gutter="20">
          <el-col :span="16">
            <el-card shadow="hover" class="card">
              <template #header>
                <div class="card-header">
                  <span class="card-title">① 选择目标岗位</span>
                  <el-tag size="small" type="info">Round 2 · 6 个方向可用</el-tag>
                </div>
              </template>

              <el-form label-position="top">
                <el-form-item label="目标岗位方向">
                  <el-select v-model="selectedRole" size="large" style="width: 100%">
                    <el-option
                      v-for="r in roles"
                      :key="r.id"
                      :label="r.name"
                      :value="r.id"
                    >
                      <div style="display: flex; justify-content: space-between; gap: 12px">
                        <span>{{ r.name }}</span>
                        <span style="color: #999; font-size: 12px">{{ r.tone }}</span>
                      </div>
                    </el-option>
                  </el-select>
                  <div class="hint" v-if="currentRole">
                    求职意向将使用:<b>{{ currentRole.intention }}</b>
                  </div>
                </el-form-item>

                <el-form-item label="自定义求职意向(可选)">
                  <el-input v-model="customIntention" placeholder="留空则使用岗位默认值" clearable />
                </el-form-item>

                <!-- Round 3 J: 简历模板库 -->
                <el-form-item label="简历排版">
                  <el-radio-group v-model="selectedTemplate" size="small">
                    <el-radio-button
                      v-for="t in templates"
                      :key="t.id"
                      :value="t.id"
                    >
                      <!-- R3-M.3: bilingual 模板加 title tooltip,提示双语字段缺失会降级 -->
                      <span
                        v-if="t.id === 'bilingual'"
                        :title="bilingualTooltip"
                      >{{ t.name }}</span>
                      <span v-else>{{ t.name }}</span>
                    </el-radio-button>
                  </el-radio-group>
                  <div class="hint" v-if="templates.length">
                    {{
                      templates.find(t => t.id === selectedTemplate)?.description
                        ?? ''
                    }}
                  </div>

                  <!-- R3-M.3: academic 模板二级选项 — 紧凑 / 详细 -->
                  <div
                    v-if="selectedTemplate === 'academic'"
                    class="academic-layout-sub"
                    style="margin-top: 8px;"
                  >
                    <span style="margin-right: 8px; color: #606266; font-size: 13px;">学术模式:</span>
                    <el-radio-group v-model="academicLayout" size="small">
                      <el-radio-button value="compact">紧凑</el-radio-button>
                      <el-radio-button value="detailed">详细</el-radio-button>
                    </el-radio-group>
                    <span style="margin-left: 8px; color: #909399; font-size: 12px;">
                      {{ academicLayout === 'compact'
                          ? '简化版:无项目名 / 无周期 / 无概述(履历表友好)'
                          : '详细版:恢复项目名 + 周期 + 概述(适合 Research Statement)' }}
                    </span>
                  </div>
                </el-form-item>

                <!-- Round 3 I: 按 JD 智能排序 -->
                <el-form-item label="智能排序">
                  <el-checkbox v-model="jdAware" size="default">
                    按 JD 智能排序(项目 / highlight / 技能组按命中数倒序)
                  </el-checkbox>
                  <div class="hint">
                    {{
                      jdAware
                        ? '将使用下方 JD 文本触发后端排序,预览显示「命中 N 关键词」角标'
                        : '不勾选则按 ROLE_CONFIG 原顺序生成(与之前一致)'
                    }}
                  </div>
                  <div class="hint" style="margin-top: 4px">
                    <el-checkbox v-model="jdAwareBadgeEnabled" :disabled="!jdAware" size="small">
                      显示「命中 N 关键词」角标(预览页)
                    </el-checkbox>
                  </div>
                </el-form-item>

                <!-- R5-C Phase 4: Agent workflow 高级开关(默认关, 不开启时 UI 字节级一致) -->
                <el-form-item label="Agent Workflow">
                  <el-switch
                    v-model="enableAgentWorkflow"
                    active-text="启用"
                    inactive-text="关闭 (默认)"
                    inline-prompt
                    style="--el-switch-on-color: #6f42c1;"
                  />
                  <el-tag
                    size="small"
                    type="info"
                    effect="plain"
                    style="margin-left: 8px"
                  >R5-C Phase 4 · 高级 / 实验性</el-tag>
                  <div class="hint">
                    {{
                      enableAgentWorkflow
                        ? '预览页将展示工具调用 / evidence / 外部简历 / bullet 评估 摘要(默认收起)'
                        : '不开启时与原 UI 字节级一致(spec §5.4 验收)'
                    }}
                  </div>
                  <div
                    v-if="enableAgentWorkflow && agentSessionId"
                    class="hint"
                    style="margin-top: 4px; font-family: monospace;"
                  >
                    session_id: <b>{{ agentSessionId.slice(0, 8) }}…</b>(前端随机生成, 不含 PII)
                  </div>
                </el-form-item>

                <el-form-item>
                  <el-button
                    type="primary"
                    size="large"
                    :loading="loading"
                    @click="onPreview"
                    style="width: 100%"
                  >
                    下一步:生成预览 →
                  </el-button>
                </el-form-item>
              </el-form>
            </el-card>
          </el-col>

          <el-col :span="8">
            <el-card shadow="hover" class="card">
              <template #header>
                <div class="card-header">
                  <span class="card-title">素材库</span>
                  <el-tag size="small" type="success">已就绪</el-tag>
                </div>
              </template>
              <template v-if="summary">
                <el-descriptions :column="1" border size="small">
                  <el-descriptions-item label="姓名">{{ summary.name }}</el-descriptions-item>
                  <el-descriptions-item label="学校">{{ summary.school }}</el-descriptions-item>
                  <el-descriptions-item label="专业">{{ summary.major }}</el-descriptions-item>
                  <el-descriptions-item label="项目数">{{ summary.project_count }}</el-descriptions-item>
                  <el-descriptions-item label="技能组">{{ summary.skill_groups.length }}</el-descriptions-item>
                  <el-descriptions-item label="荣誉数">{{ summary.honor_count }}</el-descriptions-item>
                </el-descriptions>
                <h4 style="margin-top: 16px">项目列表</h4>
                <ul class="proj-list">
                  <li v-for="p in summary.projects" :key="p.id">
                    <span class="dot"></span>
                    <span class="proj-name">{{ p.name }}</span>
                    <span class="proj-period">{{ p.period }}</span>
                  </li>
                </ul>
              </template>
              <el-skeleton v-else :rows="6" animated />
            </el-card>
          </el-col>
        </el-row>

        <!-- ============ Round 2 #2: JD 解析 · 匹配度评分 ============ -->
        <el-row :gutter="20" style="margin-top: 20px">
          <el-col :span="24">
            <el-card shadow="hover" class="card">
              <template #header>
                <div class="card-header">
                  <span class="card-title">② JD 解析 · 匹配度评分 <el-tag size="small" type="info" style="margin-left: 8px">Round 2 新增 · 可选</el-tag></span>
                  <el-tag v-if="llmHintShown" size="small" type="warning">
                    LLM 改写需后端设置 LLM_API_KEY(留空则走原文)
                  </el-tag>
                </div>
              </template>

              <el-form label-position="top">
                <el-form-item label="粘贴目标岗位 JD 文本(中文/英文均可,支持任意长度)">
                  <el-input
                    v-model="jdText"
                    type="textarea"
                    :rows="6"
                    placeholder="例如:招聘大模型评测实习生,要求熟悉 Python/PyTorch,有 LLM 评测经验,本科及以上..."
                    resize="vertical"
                  />
                </el-form-item>

                <!-- R3-G: 外部简历上传 (可选, 触发简历视角评分) -->
                <el-form-item label="或上传现有简历 (可选, 触发简历视角 have/need 分析)">
                  <ResumeUploader @parsed="onResumeParsed" @clear="onClearResume" />
                  <div v-if="externalResumeFilename" class="hint" style="margin-top: 4px">
                    已上传: <b>{{ externalResumeFilename }}</b> (评分时会展示"简历已有 / 还缺什么")
                    <el-button
                      link
                      type="danger"
                      size="small"
                      style="margin-left: 8px"
                      @click="onClearResume"
                    >清除</el-button>
                  </div>
                </el-form-item>

                <el-form-item>
                  <el-button
                    type="success"
                    :loading="jdLoading"
                    :disabled="!jdText.trim()"
                    @click="onScoreJd"
                  >
                    对当前岗位跑匹配度评分 →
                  </el-button>
                  <span class="hint" style="margin-left: 12px">
                    评分 0-100,绿色 ≥80 可放心投递,橙色 60-79 建议补充素材,红色 &lt;60 需要大幅补充
                  </span>
                </el-form-item>
              </el-form>

              <!-- 评分结果展示 -->
              <template v-if="jdResult">
                <el-divider />

                <!-- Round 3 A: 业务阈值 banner (顶部显眼位置) -->
                <el-alert
                  :type="recommendationAlertType(jdResult.recommendation)"
                  :title="recommendationAlertTitle(jdResult.recommendation)"
                  :description="recommendationAlertDetail(jdResult.recommendation)"
                  :closable="false"
                  show-icon
                  style="margin-bottom: 16px"
                >
                  <template #default>
                    <span style="color: #666; font-size: 12px">
                      阈值:≥80 强烈推荐 · 60-79 建议补充 · &lt;60 需大幅补充（Round 3.5 调优）
                    </span>
                  </template>
                </el-alert>

                <el-row :gutter="20">
                  <el-col :span="6">
                    <div class="score-box" :style="{ borderColor: scoreColor(jdResult.score) }">
                      <div class="score-value" :style="{ color: scoreColor(jdResult.score) }">
                        {{ jdResult.score }}
                      </div>
                      <div class="score-label">综合匹配分</div>
                      <el-tag :type="scoreTag(jdResult.score)" size="small" effect="dark" style="margin-top: 8px">
                        {{ jdResult.score >= 80 ? '可放心投递' : jdResult.score >= 60 ? '建议补充' : '需大幅补充' }}
                      </el-tag>
                    </div>
                  </el-col>
                  <el-col :span="6">
                    <div class="coverage-box">
                      <div class="coverage-title">三维覆盖率</div>
                      <div class="coverage-row">
                        <span class="lbl">技能</span>
                        <el-progress :percentage="Math.round(jdResult.coverage.skills * 100)" :stroke-width="10" />
                      </div>
                      <div class="coverage-row">
                        <span class="lbl">工具</span>
                        <el-progress :percentage="Math.round(jdResult.coverage.tools * 100)" :stroke-width="10" />
                      </div>
                      <div class="coverage-row">
                        <span class="lbl">领域</span>
                        <el-progress :percentage="Math.round(jdResult.coverage.domains * 100)" :stroke-width="10" />
                      </div>
                    </div>
                  </el-col>
                  <el-col :span="12">
                    <div class="kw-box">
                      <div class="kw-title">
                        <span>命中 <el-tag size="small" type="success">{{ jdResult.matched_keywords.length }}</el-tag></span>
                        <span style="margin-left: 16px">缺失 <el-tag size="small" type="danger">{{ jdResult.missing_keywords.length }}</el-tag></span>
                      </div>
                      <div class="kw-row">
                        <span class="kw-lbl">命中:</span>
                        <span v-for="k in jdResult.matched_keywords" :key="'m-'+k" class="kw-chip matched">{{ k }}</span>
                        <span v-if="jdResult.matched_keywords.length === 0" class="hint">(无)</span>
                      </div>
                      <div class="kw-row">
                        <span class="kw-lbl">缺失:</span>
                        <span v-for="k in jdResult.missing_keywords" :key="'x-'+k" class="kw-chip missing">{{ k }}</span>
                        <span v-if="jdResult.missing_keywords.length === 0" class="hint">(无)</span>
                      </div>
                    </div>
                  </el-col>
                </el-row>

                <!-- R3-G: 简历视角 (上传简历后才有) -->
                <template v-if="jdResult.resume_perspective">
                  <el-divider />
                  <div class="rp-box">
                    <div class="rp-title">
                      <span>
                        <el-tag size="small" type="info" effect="dark">R3-G 简历视角</el-tag>
                        基于已上传简历的"已有 / 还缺"分析
                      </span>
                      <span style="margin-left: 16px">
                        <el-tag size="small" type="success">已有 {{ jdResult.resume_perspective.have_count }}</el-tag>
                        <el-tag size="small" type="danger" style="margin-left: 4px">还缺 {{ jdResult.resume_perspective.need_count }}</el-tag>
                      </span>
                    </div>
                    <div class="rp-row">
                      <span class="rp-lbl">简历里有:</span>
                      <span v-for="k in jdResult.resume_perspective.have_keywords" :key="'rp-h-'+k" class="kw-chip matched">{{ k }}</span>
                      <span v-if="jdResult.resume_perspective.have_keywords.length === 0" class="hint">(无)</span>
                    </div>
                    <div class="rp-row">
                      <span class="rp-lbl">简历里没提 (已扣除素材库能提供的):</span>
                      <span v-for="k in jdResult.resume_perspective.need_keywords" :key="'rp-n-'+k" class="kw-chip missing">{{ k }}</span>
                      <span v-if="jdResult.resume_perspective.need_keywords.length === 0" class="hint">(无 — 简历覆盖所有 JD 要求)</span>
                    </div>
                  </div>
                </template>

                <el-alert
                  v-if="jdResult.suggestions.length"
                  type="info"
                  :closable="false"
                  style="margin-top: 16px"
                >
                  <template #title>
                    <b>补充建议</b>
                  </template>
                  <ul style="margin: 4px 0 0 16px; padding: 0; line-height: 1.8">
                    <li v-for="(s, i) in jdResult.suggestions" :key="i">{{ s }}</li>
                  </ul>
                </el-alert>
              </template>
            </el-card>
          </el-col>
        </el-row>
      </template>

      <!-- ============ 阶段 2: 预览 ============ -->
      <template v-else-if="stage === 'preview' && previewData">
        <el-card shadow="hover" class="card">
          <template #header>
            <div class="card-header">
              <span class="card-title">② 预览 · 确认要写进 .docx 的内容</span>
              <div>
                <el-button @click="backToSelect" size="small">← 返回修改</el-button>
              </div>
            </div>
          </template>

          <el-alert
            type="warning"
            :closable="false"
            title="请仔细 review 下方每个模块,这是将要写入 .docx 的全部内容。确认无误后再点底部「确认下载」。"
            style="margin-bottom: 16px"
          />

          <!-- R5-C Phase 4: Agent Workflow 诊断面板
               默认全部收起; 仅在 enable_agent_workflow=true 且后端真返回 agent_summary 时渲染。
               隐私: 仅展示摘要 / 计数 / 关键词 / 短建议, 不展示 evidence.text / bullet 原文
                     / JD 原文 / 简历原文 / 真实姓名手机邮箱(spec §6.4)。 -->
          <el-collapse
            v-if="hasAgentPanel && previewData.agent_summary"
            v-model="agentPanelActive"
            class="agent-panel"
            style="margin-bottom: 16px"
          >
            <el-collapse-item name="agent_overview" title="Agent Workflow 诊断 (高级 / 实验性)">
              <div class="agent-section">
                <div class="agent-section-title">1) Request / 耗时</div>
                <div class="agent-row">
                  <span class="agent-lbl">request_id:</span>
                  <code class="agent-mono">{{ previewData.agent_summary.request_id }}</code>
                  <el-button
                    size="small"
                    link
                    type="primary"
                    @click="copyRequestId"
                  >复制</el-button>
                </div>
                <div class="agent-row">
                  <span class="agent-lbl">步骤数:</span>
                  <el-tag size="small" type="info" effect="plain">
                    {{ previewData.agent_summary.steps_executed }}
                  </el-tag>
                  <span class="agent-lbl" style="margin-left: 16px">总耗时:</span>
                  <el-tag size="small" type="info" effect="plain">
                    {{ previewData.agent_summary.latency_ms }} ms
                  </el-tag>
                </div>
              </div>

              <div class="agent-section">
                <div class="agent-section-title">2) Fallback 状态</div>
                <el-tag
                  v-if="!previewData.agent_summary.fallback_used"
                  type="success"
                  size="small"
                  effect="dark"
                >✓ {{ fallbackText() }}</el-tag>
                <el-tag
                  v-else
                  type="warning"
                  size="small"
                  effect="dark"
                >⚠ {{ fallbackText() }}</el-tag>
              </div>

              <div class="agent-section">
                <div class="agent-section-title">3) 有效工具调用</div>
                <div class="agent-row">
                  <span class="agent-lbl">影响 preview 的工具 ({{ agentToolsUsed.length }} 个):</span>
                  <el-tag
                    v-for="t in agentToolsUsed"
                    :key="t"
                    size="small"
                    type="info"
                    effect="plain"
                    style="margin-left: 4px"
                  >{{ t }}</el-tag>
                  <span
                    v-if="agentToolsUsed.length === 0"
                    class="hint"
                    style="margin-left: 4px"
                  >无(展示型工具不计)</span>
                </div>
                <div class="hint" style="margin-top: 4px">
                  tools_used 只列 affects_preview=True 且 status=success 的工具(R5-B Phase 2A 语义)
                </div>
              </div>

              <div v-if="hasEvidence" class="agent-section">
                <div class="agent-section-title">4) Evidence 来源统计 (不展示原文)</div>
                <div class="agent-row">
                  <span class="agent-lbl">来源分桶:</span>
                  <el-tag size="small" effect="plain">project {{ evidenceStats.bySource.project }}</el-tag>
                  <el-tag size="small" effect="plain" style="margin-left: 4px">skill {{ evidenceStats.bySource.skill }}</el-tag>
                  <el-tag size="small" effect="plain" style="margin-left: 4px">honor {{ evidenceStats.bySource.honor }}</el-tag>
                  <el-tag size="small" effect="plain" style="margin-left: 4px">cert {{ evidenceStats.bySource.cert }}</el-tag>
                </div>
                <div class="agent-row" style="margin-top: 4px">
                  <span class="agent-lbl">总命中关键词:</span>
                  <el-tag size="small" type="success" effect="plain">{{ evidenceStats.totalMatchedKw }}</el-tag>
                  <span class="agent-lbl" style="margin-left: 16px">最高 confidence:</span>
                  <el-tag size="small" type="info" effect="plain">
                    {{ evidenceStats.maxConfidence.toFixed(3) }}
                  </el-tag>
                  <span class="agent-lbl" style="margin-left: 16px">平均 confidence:</span>
                  <el-tag size="small" type="info" effect="plain">
                    {{ evidenceStats.avgConfidence.toFixed(3) }}
                  </el-tag>
                </div>
                <div class="hint" style="margin-top: 4px">
                  evidence summary 共 {{ evidenceStats.total }} 条; 原文(text)未在此面板展示(spec §6.4)
                </div>
              </div>

              <div v-if="hasExtPerspective && extPerspective" class="agent-section">
                <div class="agent-section-title">5) 外部简历诊断 (have / need / gap)</div>
                <div class="agent-row">
                  <span class="agent-lbl">已有:</span>
                  <el-tag size="small" type="success" effect="plain">{{ extPerspective.counts.have }}</el-tag>
                  <span class="agent-lbl" style="margin-left: 12px">缺:</span>
                  <el-tag size="small" type="danger" effect="plain">{{ extPerspective.counts.need }}</el-tag>
                  <span class="agent-lbl" style="margin-left: 12px">素材库可补:</span>
                  <el-tag size="small" type="warning" effect="plain">{{ extPerspective.counts.materials_can_cover }}</el-tag>
                  <span class="agent-lbl" style="margin-left: 12px">简历独有:</span>
                  <el-tag size="small" type="info" effect="plain">{{ extPerspective.counts.resume_only }}</el-tag>
                </div>
                <div
                  v-if="extPerspective.have_keywords.length"
                  class="agent-row"
                  style="margin-top: 4px"
                >
                  <span class="agent-lbl">已有:</span>
                  <span
                    v-for="k in extPerspective.have_keywords"
                    :key="'ah-'+k"
                    class="kw-chip matched"
                    style="margin-left: 2px"
                  >{{ k }}</span>
                </div>
                <div
                  v-if="extPerspective.need_keywords.length"
                  class="agent-row"
                  style="margin-top: 4px"
                >
                  <span class="agent-lbl">还缺:</span>
                  <span
                    v-for="k in extPerspective.need_keywords"
                    :key="'an-'+k"
                    class="kw-chip missing"
                    style="margin-left: 2px"
                  >{{ k }}</span>
                </div>
                <div
                  v-if="extPerspective.suggestions.length"
                  class="agent-row"
                  style="margin-top: 6px"
                >
                  <span class="agent-lbl">建议:</span>
                  <ul class="agent-suggestion-list">
                    <li
                      v-for="(s, i) in extPerspective.suggestions"
                      :key="'as-'+i"
                    >{{ s }}</li>
                  </ul>
                </div>
              </div>

              <div v-if="hasBulletEvaluations" class="agent-section">
                <div class="agent-section-title">6) Bullet 评估摘要 (不展示原 bullet)</div>
                <div class="agent-row">
                  <span class="agent-lbl">评估条数:</span>
                  <el-tag size="small" type="info" effect="plain">{{ bulletStats.total }}</el-tag>
                  <span class="agent-lbl" style="margin-left: 12px">总命中:</span>
                  <el-tag size="small" type="success" effect="plain">{{ bulletStats.totalMatched }}</el-tag>
                  <span class="agent-lbl" style="margin-left: 12px">总缺失:</span>
                  <el-tag size="small" type="danger" effect="plain">{{ bulletStats.totalMissing }}</el-tag>
                </div>
                <div
                  v-for="proj in bulletStats.byProject"
                  :key="'bp-'+proj.project_id"
                  class="agent-row"
                  style="margin-top: 6px"
                >
                  <span class="agent-lbl">项目 {{ proj.project_id }}:</span>
                  <el-tag size="small" type="info" effect="plain">{{ proj.total }} 条</el-tag>
                  <span style="margin-left: 4px; color: #67c23a">命中 {{ proj.matched }}</span>
                  <span style="margin-left: 4px; color: #f56c6c">缺 {{ proj.missing }}</span>
                  <span
                    v-if="proj.topSuggestion"
                    class="hint"
                    style="margin-left: 8px"
                  >→ {{ proj.topSuggestion }}</span>
                </div>
                <div class="hint" style="margin-top: 4px">
                  仅展示每条 bullet 的 matched / missing 计数与 1 句建议; bullet 原文未在此面板展示(spec §6.4)
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>

          <el-collapse v-model="defaultActive">
            <el-collapse-item
              v-for="(s, idx) in previewData.sections"
              :key="idx"
              :name="s.type"
              :title="`${idx + 1}. ${s.title}`"
            >
              <!-- Header:姓名 + 联系方式 -->
              <template v-if="isHeader(s)">
                <div class="preview-header">
                  <div class="preview-name">{{ s.content.name }}</div>
                  <div class="preview-intention">求职意向:{{ s.content.intention }}</div>
                  <div class="preview-contact">{{ s.content.contact }}</div>
                </div>
              </template>

              <!-- Education -->
              <template v-else-if="s.type === 'education'">
                <div class="preview-line-bold">{{ s.content.line }}</div>
                <div v-if="s.content.courses" class="preview-line">
                  <span class="lbl">核心课程:</span>{{ s.content.courses }}
                </div>
                <ul v-if="s.content.highlights?.length" class="bullet">
                  <li v-for="(h, i) in s.content.highlights" :key="i">{{ h }}</li>
                </ul>
              </template>

              <!-- Project Group -->
              <template v-else-if="isProjectGroup(s)">
                <div v-for="(p, pi) in s.content.projects" :key="pi" class="preview-project">
                  <div class="preview-line-bold">
                    {{ p.title }} <span class="role">| {{ p.content.role }}</span>
                    <span
                      v-if="showProjectBadge(pi)"
                      class="match-badge"
                    >命中 {{ projectMatchCount(pi) }} 关键词</span>
                  </div>
                  <div class="preview-meta">{{ p.content.period }}</div>
                  <div v-if="p.content.summary" class="preview-line">{{ p.content.summary }}</div>
                  <ul v-if="p.content.highlights?.length" class="bullet">
                    <li v-for="(h, hi) in p.content.highlights" :key="hi">{{ h }}</li>
                  </ul>
                </div>
              </template>

              <!-- Skills -->
              <template v-else-if="isSkills(s)">
                <div v-for="(g, gi) in s.content.groups" :key="gi" class="preview-line">
                  <span class="lbl">{{ g.label }}:</span>
                  <span v-for="(item, ii) in g.items" :key="ii" class="skill-chip">{{ item }}</span>
                  <span
                    v-if="showSkillBadge(gi)"
                    class="match-badge"
                  >命中 {{ skillMatchCount(gi) }} 关键词</span>
                </div>
              </template>

              <!-- Honors / Self Eval (列表型) -->
              <template v-else-if="isList(s)">
                <ul class="bullet">
                  <li v-for="(item, i) in (s.content.items || s.content.sentences)" :key="i">{{ item }}</li>
                </ul>
              </template>

              <template v-else>
                <pre class="raw">{{ JSON.stringify(s.content, null, 2) }}</pre>
              </template>
            </el-collapse-item>
          </el-collapse>

          <el-divider />

          <div class="actions">
            <el-button @click="backToSelect">← 返回修改</el-button>
            <el-button
              type="primary"
              size="large"
              :loading="loading"
              @click="onConfirmDownload"
            >
              ✓ 确认下载 .docx
            </el-button>
          </div>
        </el-card>
      </template>

      <!-- ============ 阶段 3: 完成 ============ -->
      <template v-else-if="stage === 'done' && lastDownloaded">
        <el-card shadow="hover" class="card">
          <el-result icon="success" title="已生成并下载" sub-title="请到浏览器下载目录查看 .docx 文件">
            <template #extra>
              <el-descriptions :column="1" border style="text-align: left">
                <el-descriptions-item label="文件名">{{ lastDownloaded.name }}</el-descriptions-item>
                <el-descriptions-item label="大小">{{ formatSize(lastDownloaded.size) }}</el-descriptions-item>
                <el-descriptions-item label="时间">{{ lastDownloaded.time }}</el-descriptions-item>
              </el-descriptions>
              <div style="margin-top: 20px">
                <el-button @click="startOver" type="primary">再来一份(其他岗位)</el-button>
                <el-button @click="onPreview">基于此岗位再生成一份</el-button>
              </div>
            </template>
          </el-result>
        </el-card>
      </template>
    </main>
  </div>
</template>

<style>
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "微软雅黑", sans-serif;
  background: #f5f7fa;
  color: #303133;
}
.layout { min-height: 100vh; }
.topbar {
  background: linear-gradient(135deg, #1f4e79 0%, #2e75b6 100%);
  color: white;
  padding: 16px 40px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  flex-wrap: wrap;
  gap: 16px;
}
.brand { display: flex; align-items: center; gap: 16px; }
.logo {
  width: 48px; height: 48px;
  background: rgba(255,255,255,0.2);
  border: 2px solid rgba(255,255,255,0.4);
  border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 16px; letter-spacing: 1px;
}
.title-block h1 { margin: 0; font-size: 22px; font-weight: 600; }
.subtitle { margin: 2px 0 0; font-size: 13px; opacity: 0.85; }
.stage-indicator { min-width: 360px; }
.main {
  max-width: 1280px;
  margin: 24px auto;
  padding: 0 24px;
}
.card { border-radius: 8px; }
.card-header {
  display: flex; align-items: center; justify-content: space-between;
}
.card-title { font-weight: 600; font-size: 16px; }
.hint { font-size: 12px; color: #909399; margin-top: 4px; }
.proj-list { list-style: none; padding: 0; margin: 0; }
.proj-list li {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 0; border-bottom: 1px solid #f0f0f0; font-size: 13px;
}
.proj-list li:last-child { border-bottom: none; }
.dot { width: 6px; height: 6px; background: #2e75b6; border-radius: 50%; flex-shrink: 0; }
.proj-name { flex: 1; }
.proj-period { color: #909399; font-size: 12px; flex-shrink: 0; }

/* 预览样式 */
.preview-header { text-align: center; padding: 8px 0 12px; }
.preview-name { font-size: 22px; font-weight: 700; color: #1f4e79; }
.preview-intention { color: #1f4e79; margin-top: 4px; font-size: 14px; }
.preview-contact { color: #666; font-size: 13px; margin-top: 4px; }
.preview-line { line-height: 1.7; margin: 4px 0; }
.preview-line-bold { font-weight: 600; margin: 6px 0 2px; color: #303133; }
.preview-meta { color: #888; font-style: italic; font-size: 12px; margin-bottom: 4px; }
.preview-project {
  border-left: 3px solid #e0e0e0;
  padding: 4px 0 8px 12px;
  margin: 4px 0 8px;
}
.role { color: #888; font-weight: 400; font-size: 12px; }
.bullet { margin: 4px 0 4px 20px; padding: 0; }
.bullet li { line-height: 1.7; font-size: 13px; }
.lbl { font-weight: 600; color: #555; margin-right: 4px; }
.skill-chip {
  display: inline-block;
  background: #ecf5ff;
  color: #1f4e79;
  padding: 2px 8px;
  margin: 2px 4px 2px 0;
  border-radius: 4px;
  font-size: 12px;
}
.raw {
  background: #f5f5f5;
  padding: 12px;
  border-radius: 4px;
  font-size: 12px;
  overflow: auto;
}
.actions {
  display: flex;
  justify-content: space-between;
  margin-top: 16px;
}

/* ===== Round 2 #2: JD 评分卡 ===== */
.score-box {
  border: 3px solid #e0e0e0;
  border-radius: 8px;
  padding: 16px;
  text-align: center;
  height: 100%;
}
.score-value {
  font-size: 56px;
  font-weight: 700;
  line-height: 1;
}
.score-label {
  color: #888;
  font-size: 13px;
  margin-top: 4px;
}
.coverage-box { padding: 8px 0; }
.coverage-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
  color: #303133;
}
.coverage-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.coverage-row .lbl {
  width: 36px;
  font-size: 13px;
  color: #555;
  flex-shrink: 0;
}
.coverage-row .el-progress { flex: 1; }
.kw-box { padding: 8px 0; }
.kw-title {
  display: flex;
  gap: 4px;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 12px;
  color: #303133;
}
.kw-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
  font-size: 13px;
}
.kw-lbl {
  font-weight: 600;
  color: #555;
  margin-right: 4px;
  min-width: 36px;
}
.kw-chip {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  margin: 2px 0;
}
.kw-chip.matched {
  background: #f0f9eb;
  color: #67c23a;
  border: 1px solid #e1f3d8;
}
.kw-chip.missing {
  background: #fef0f0;
  color: #f56c6c;
  border: 1px solid #fde2e2;
}

/* ===== Round 3 I: JD 命中角标 ===== */
.match-badge {
  display: inline-block;
  margin-left: 8px;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 500;
  background: #fdf6ec;
  color: #e6a23c;
  border: 1px solid #faecd8;
  vertical-align: middle;
}

/* ===== R5-C Phase 4: Agent Workflow 诊断面板 =====
   风格克制: 单色边框 + 浅色背景, 区别于主预览内容(避免视觉噪声) */
.agent-panel {
  border: 1px solid #e4e2f3;
  border-radius: 6px;
  background: #fafafd;
  padding: 0 4px;
}
.agent-panel :deep(.el-collapse-item__header) {
  font-weight: 600;
  font-size: 14px;
  color: #4a3c8c;
}
.agent-panel :deep(.el-collapse-item__wrap) {
  background: #ffffff;
  border-top: 1px dashed #e4e2f3;
}
.agent-section {
  padding: 8px 4px 12px;
  border-bottom: 1px dashed #eee;
}
.agent-section:last-child {
  border-bottom: none;
}
.agent-section-title {
  font-size: 13px;
  font-weight: 600;
  color: #4a3c8c;
  margin-bottom: 6px;
  letter-spacing: 0.3px;
}
.agent-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  line-height: 1.8;
}
.agent-lbl {
  font-weight: 600;
  color: #555;
  font-size: 12px;
}
.agent-mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  background: #f0eef8;
  padding: 1px 6px;
  border-radius: 4px;
  color: #4a3c8c;
  font-size: 12px;
  word-break: break-all;
}
.agent-suggestion-list {
  margin: 2px 0 0 18px;
  padding: 0;
  font-size: 12px;
  color: #606266;
  line-height: 1.7;
  width: 100%;
}
.agent-suggestion-list li {
  margin: 1px 0;
}
</style>
