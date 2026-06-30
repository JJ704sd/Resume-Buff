<script setup lang="ts">
/**
 * Round 6-A Phase 3 — 简历面试官主聊天栏
 * + Round 6-B Phase 6 — frontend 最小呈现 (spec §9)
 *
 * Props:
 *   - targetRole        当前选中的 6 role id 之一(从 App.vue 透传)
 *   - jdText            用户粘贴的 JD 文本(空时禁用启动按钮)
 *   - externalResumeText 可选外部简历全文(start 时随 jd_text 一并送进后端)
 * Emits:
 *   - refresh-match     保存素材后,通知 App.vue 重跑 jdApi.match
 *   - refresh-preview   保存素材后,通知 App.vue 重跑 resumeApi.preview
 *
 * R5-E 保护(spec §3.3): 不 import AgentSummary / EvidenceSummary 等 workflow 诊断类型,
 * 仅消费自己新增的 5 个 InterviewXxx 类型 + R6-B 模式字段。
 *
 * R6-B Phase 6 边界(spec §9):
 *   - 不显示 Agent Workflow / trace / schema / ToolResult
 *   - 不显示 prompt / raw response / source_span 明文
 *   - 移动端 drawer 不被 toggle/warning 挤坏(都用普通 div + el-tag,无 portal)
 */
import { ref, computed, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import {
  interviewApi,
  type InterviewDraftCard as DraftCardData,
  type InterviewGap,
  type InterviewMessage,
  type InterviewMode,
  type InterviewProgress,
  type InterviewState,
} from '../api'
import InterviewProgressPills from './InterviewProgressPills.vue'
import InterviewDraftCard from './InterviewDraftCard.vue'

const props = defineProps<{
  targetRole: string
  jdText: string
  externalResumeText?: string
}>()

const emit = defineEmits<{
  'refresh-match': []
  'refresh-preview': []
}>()

// ---- 内部状态 ----
const sessionId = ref('')
const state = ref<InterviewState>('EMPTY')
const selectedGap = ref<InterviewGap | null>(null)
type ChatLine = { role: 'assistant' | 'user'; text: string; quickReplies?: string[] }
const messages = ref<ChatLine[]>([])
const progress = ref<InterviewProgress>({
  captured: {},
  turn_count: 0,
  can_draft: false,
})
const draftCard = ref<DraftCardData | null>(null)
const userInput = ref('')
const loading = ref(false)
const drawerVisible = ref(false)  // 移动端控制
const chatScrollRef = ref<HTMLElement | null>(null)

// ----- R6-B Phase 6(spec §9): 智能抽取 toggle + 抽取模式状态 -----
// EMPTY 状态下切换;start 后即固定(模式由 session.interview_mode 决定,
// 老路径/无 key 时 mode_warning 非 null → 显示"已回退规则模式")
const enableInterviewLlm = ref(false)
const interviewMode = ref<InterviewMode>('rules')
const modeWarning = ref<string | null>(null)

const canStart = computed(() => Boolean(props.targetRole && props.jdText.trim()))
const canSubmitAnswer = computed(
  () => state.value === 'ASKING' && userInput.value.trim().length > 0 && !loading.value,
)
// header 三态标签颜色 + 文案(spec §9):
//   1. modeWarning 非空(无论 mode 如何) → "已回退规则模式" warning
//   2. 无 warning + llm_assisted → "智能抽取" success
//   3. 无 warning + rules       → "规则模式" info
const modeTagInfo = computed<{
  show: boolean
  label: string
  type: 'info' | 'success' | 'warning'
}>(() => {
  const show = state.value !== 'EMPTY' && state.value !== 'DIAGNOSING'
  if (!show) return { show: false, label: '', type: 'info' }
  if (modeWarning.value) {
    return { show: true, label: '已回退规则模式', type: 'warning' }
  }
  if (interviewMode.value === 'llm_assisted') {
    return { show: true, label: '智能抽取', type: 'success' }
  }
  return { show: true, label: '规则模式', type: 'info' }
})

// 滚动消息到底部
async function scrollToBottom() {
  await nextTick()
  if (chatScrollRef.value) {
    chatScrollRef.value.scrollTop = chatScrollRef.value.scrollHeight
  }
}

// 启动面试
async function onStart() {
  if (!canStart.value) {
    ElMessage.warning('请先粘贴 JD 文本并选择目标岗位')
    return
  }
  loading.value = true
  state.value = 'DIAGNOSING'
  try {
    // R6-B Phase 2(spec §5.3): 透传 enable_interview_llm 开关;
    // 老路径不传=False 字节级一致
    const res = await interviewApi.start({
      target_role: props.targetRole,
      jd_text: props.jdText.trim(),
      enable_interview_llm: enableInterviewLlm.value,
    })
    sessionId.value = res.session_id
    state.value = res.state as InterviewState
    selectedGap.value = res.selected_gap ?? null
    progress.value = res.progress
    // R6-B Phase 2(spec §5.3): 抽取模式从响应里读,展示在 header
    interviewMode.value = res.interview_mode ?? 'rules'
    modeWarning.value = res.mode_warning ?? null
    messages.value = []
    if (res.message) {
      messages.value.push({
        role: 'assistant',
        text: res.message.text,
        quickReplies: res.message.quick_replies,
      })
    }
    scrollToBottom()
  } catch (e: any) {
    state.value = 'EMPTY'
    ElMessage.error(`启动面试官失败: ${e?.response?.data?.detail ?? e?.message ?? '未知错误'}`)
  } finally {
    loading.value = false
  }
}

// 用户提交 answer
async function onSendAnswer() {
  if (!canSubmitAnswer.value) return
  const text = userInput.value.trim()
  userInput.value = ''
  messages.value.push({ role: 'user', text })
  await sendReply('answer', text)
}

// 快捷回复 chip 点击
async function onQuickReply(reply: string) {
  if (state.value !== 'ASKING' || loading.value) return
  // 一些 chip 是动作,不是字面 answer 文本
  const actionMap: Record<string, { action: 'answer' | 'skip_question' | 'rephrase_question' | 'draft_now'; msg: string }> = {
    '跳过这个问题': { action: 'skip_question', msg: '' },
    '换个问法': { action: 'rephrase_question', msg: '' },
    '整理成素材': { action: 'draft_now', msg: '' },
  }
  const mapped = actionMap[reply]
  if (mapped) {
    messages.value.push({ role: 'user', text: reply })
    await sendReply(mapped.action, mapped.msg)
  } else {
    // 当成 answer
    messages.value.push({ role: 'user', text: reply })
    await sendReply('answer', reply)
  }
}

// 切换缺口
async function onSwitchGap() {
  messages.value.push({ role: 'user', text: '换一个缺口' })
  await sendReply('switch_gap', '')
}

// 通用 reply 调度
async function sendReply(action: 'answer' | 'skip_question' | 'rephrase_question' | 'switch_gap' | 'draft_now', msg: string) {
  if (!sessionId.value) return
  loading.value = true
  try {
    const res = await interviewApi.reply({
      session_id: sessionId.value,
      message: msg,
      action,
    })
    state.value = res.state as InterviewState
    if (res.progress) progress.value = res.progress
    if (res.message) {
      messages.value.push({
        role: 'assistant',
        text: res.message.text,
        quickReplies: res.message.quick_replies,
      })
    }
    // 强制 draft 时,拉一次 draft_card
    if (res.force_draft || (res.can_draft && action === 'draft_now')) {
      await fetchDraftCard()
    }
    scrollToBottom()
  } catch (e: any) {
    ElMessage.error(`回复失败: ${e?.response?.data?.detail ?? e?.message ?? '未知错误'}`)
  } finally {
    loading.value = false
  }
}

async function fetchDraftCard() {
  if (!sessionId.value) return
  try {
    const res = await interviewApi.draft(sessionId.value)
    draftCard.value = res.draft_card
    state.value = res.state as InterviewState
  } catch (e: any) {
    // can_draft=False 的 400 已在 chip/reply 流程里前置处理
    ElMessage.error(`生成草稿失败: ${e?.response?.data?.detail ?? e?.message ?? '未知错误'}`)
  }
}

// 保存草稿 → 写库 → 触发刷新
async function onSaveCard(edited: DraftCardData) {
  if (!sessionId.value) return
  loading.value = true
  try {
    const res = await interviewApi.saveCard({
      session_id: sessionId.value,
      edited_card: edited,
      save_mode: 'append_project',
    })
    if (res.ok) {
      state.value = 'SAVED'
      messages.value.push({
        role: 'assistant',
        text: `已写入素材库 (project id: ${res.material_ref.id})。后续可在素材库概览里看到这条新项目。`,
      })
      // 触发 App.vue 刷新匹配度评分 + 预览
      if (res.refresh?.should_refresh_match) emit('refresh-match')
      if (res.refresh?.should_refresh_preview) emit('refresh-preview')
      ElMessage.success('已保存到素材库')
      scrollToBottom()
    }
  } catch (e: any) {
    ElMessage.error(`保存失败: ${e?.response?.data?.detail ?? e?.message ?? '未知错误'}`)
  } finally {
    loading.value = false
  }
}

// 继续追问(从 DRAFT_READY 回到 ASKING)
function onContinueAsking() {
  state.value = 'ASKING'
  userInput.value = ''
}

// 丢弃 → 重置
function onDiscard() {
  state.value = 'EMPTY'
  sessionId.value = ''
  selectedGap.value = null
  messages.value = []
  progress.value = { captured: {}, turn_count: 0, can_draft: false }
  draftCard.value = null
  userInput.value = ''
  // R6-B Phase 6: 丢弃后回到默认状态;mode 不保留(下一次 start 重新选)
  interviewMode.value = 'rules'
  modeWarning.value = null
  ElMessage.info('已丢弃本次对话')
}

// 移动端抽屉显隐
function openDrawer() { drawerVisible.value = true }
function closeDrawer() { drawerVisible.value = false }

// 当父层 jdText / targetRole 变化时,如果在 EMPTY 状态,清掉旧数据(下次 start 会拿最新值)
watch(
  () => [props.jdText, props.targetRole],
  () => {
    if (state.value === 'EMPTY' || state.value === 'SAVED') {
      messages.value = []
      selectedGap.value = null
      draftCard.value = null
      progress.value = { captured: {}, turn_count: 0, can_draft: false }
      // R6-B Phase 6: 父层变更时同步重置 mode 标签
      interviewMode.value = 'rules'
      modeWarning.value = null
    }
  },
)
</script>

<template>
  <!-- 桌面端:固定容器由父级 .interview-sidecar 包装;移动端:本组件自身在 FAB + drawer 里 -->
  <div class="interview-panel">
    <div class="ip-header">
      <span class="ip-title">简历面试官</span>
      <!-- R6-B Phase 6(spec §9): header 显示当前抽取模式(三态);会话未开始时显示静态 β 标签 -->
      <el-tag
        v-if="modeTagInfo.show"
        :type="modeTagInfo.type"
        size="small"
        effect="plain"
        :title="modeWarning ?? ''"
      >{{ modeTagInfo.label }}</el-tag>
      <el-tag v-else size="small" type="info" effect="plain">Round 6-A · β</el-tag>
    </div>

    <!-- EMPTY -->
    <div v-if="state === 'EMPTY'" class="ip-empty">
      <div class="ip-empty-icon">💬</div>
      <div class="ip-empty-text">看到一个值得补的缺口?</div>
      <div class="ip-empty-text">让面试官问 3 个问题,帮你整理成可写入素材库的项目卡。</div>
      <el-button
        type="primary"
        :disabled="!canStart"
        :loading="loading"
        style="margin-top: 12px"
        @click="onStart"
      >让面试官帮我补经历</el-button>
      <div v-if="!canStart" class="ip-empty-hint">
        请先在上方选择目标岗位并粘贴 JD 文本
      </div>

      <!-- R6-B Phase 6(spec §9): 智能抽取 toggle,默认关闭;
           tooltip 解释 fallback 行为;不影响移动 drawer 布局(普通 div + flex,不 portal) -->
      <div class="ip-toggle-row">
        <el-switch
          v-model="enableInterviewLlm"
          size="small"
          inline-prompt
          active-text="智能抽取"
          inactive-text="规则模式"
        />
        <el-tooltip
          content="实验功能:有 key 时帮助识别你回答中的多个事实;失败会自动回到规则模式。"
          placement="top"
        >
          <span class="ip-toggle-hint">?</span>
        </el-tooltip>
      </div>
    </div>

    <!-- DIAGNOSING -->
    <div v-else-if="state === 'DIAGNOSING'" class="ip-loading">
      <el-icon class="is-loading"><i-ep-loading /></el-icon>
      <span>正在找最值得补的一块经历证据...</span>
    </div>

    <!-- 已有缺口信息(ASKING / DRAFT_READY / SAVED 都显示) -->
    <div v-if="selectedGap && state !== 'EMPTY' && state !== 'DIAGNOSING'" class="ip-gap">
      <div class="ip-gap-label">
        当前缺口:<b>{{ selectedGap.label }}</b>
        <el-tag size="small" effect="plain">{{ selectedGap.tier }}</el-tag>
      </div>
      <div class="ip-gap-reason">{{ selectedGap.reason }}</div>
      <InterviewProgressPills :progress="progress" />
    </div>

    <!-- 消息流(ASKING / DRAFT_READY / SAVED) -->
    <div
      v-if="state !== 'EMPTY' && state !== 'DIAGNOSING'"
      ref="chatScrollRef"
      class="ip-chat"
    >
      <div
        v-for="(m, i) in messages"
        :key="i"
        class="ip-msg"
        :class="m.role === 'user' ? 'ip-msg-user' : 'ip-msg-bot'"
      >
        <div class="ip-msg-text">{{ m.text }}</div>
        <div
          v-if="m.role === 'assistant' && m.quickReplies && m.quickReplies.length && state === 'ASKING'"
          class="ip-quick"
        >
          <el-tag
            v-for="r in m.quickReplies"
            :key="r"
            class="ip-quick-chip"
            :type="['整理成素材', '换个问法', '跳过这个问题'].includes(r) ? 'info' : ''"
            effect="plain"
            @click="onQuickReply(r)"
          >{{ r }}</el-tag>
        </div>
      </div>
    </div>

    <!-- ASKING 输入区 -->
    <div v-if="state === 'ASKING'" class="ip-input">
      <el-input
        v-model="userInput"
        type="textarea"
        :rows="2"
        placeholder="像讲给面试官听一样回答,不用很正式"
        maxlength="2000"
        show-word-limit
        @keyup.enter.exact.prevent="onSendAnswer"
      />
      <div class="ip-input-actions">
        <el-button size="small" :disabled="loading" @click="onSwitchGap">换一个缺口</el-button>
        <el-button
          type="primary"
          size="small"
          :disabled="!canSubmitAnswer"
          :loading="loading"
          @click="onSendAnswer"
        >发送</el-button>
      </div>
    </div>

    <!-- DRAFT_READY 显示草稿卡 -->
    <div v-else-if="state === 'DRAFT_READY' && draftCard" class="ip-draft">
      <InterviewDraftCard
        :draft-card="draftCard"
        :target-role="targetRole"
        @save="onSaveCard"
        @continue-asking="onContinueAsking"
        @discard="onDiscard"
        @switch-gap="onSwitchGap"
      />
    </div>

    <!-- SAVED 提示 -->
    <div v-else-if="state === 'SAVED'" class="ip-saved">
      <el-result icon="success" title="已写入素材库">
        <template #extra>
          <el-button size="small" @click="onDiscard">开始新对话</el-button>
        </template>
      </el-result>
    </div>
  </div>
</template>

<style scoped>
.interview-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #ffffff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  overflow: hidden;
  font-size: 13px;
}
.ip-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: linear-gradient(135deg, #1f4e79 0%, #2e75b6 100%);
  color: #fff;
}
.ip-title {
  font-weight: 600;
  font-size: 14px;
  letter-spacing: 0.5px;
}
.ip-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 24px;
  color: #606266;
}
.ip-empty-icon {
  font-size: 36px;
  margin-bottom: 8px;
}
.ip-empty-text {
  font-size: 13px;
  line-height: 1.7;
}
.ip-empty-hint {
  margin-top: 8px;
  font-size: 12px;
  color: #909399;
}
/* R6-B Phase 6(spec §9): 智能抽取 toggle 行 — flex 横排,小尺寸,不撑高 EMPTY 卡片 */
.ip-toggle-row {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #606266;
}
.ip-toggle-hint {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #909399;
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  cursor: help;
  user-select: none;
}
.ip-loading {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #606266;
  padding: 24px;
}
.ip-gap {
  padding: 10px 14px;
  border-bottom: 1px dashed #e0e0e0;
  background: #fafbfc;
}
.ip-gap-label {
  font-size: 12px;
  color: #303133;
  display: flex;
  align-items: center;
  gap: 6px;
}
.ip-gap-reason {
  font-size: 11px;
  color: #909399;
  margin-top: 2px;
  line-height: 1.5;
}
.ip-chat {
  flex: 1;
  overflow-y: auto;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 200px;
  max-height: calc(100vh - 360px);
}
.ip-msg {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 88%;
}
.ip-msg-text {
  padding: 8px 10px;
  border-radius: 8px;
  line-height: 1.6;
  word-break: break-word;
  white-space: pre-wrap;
}
.ip-msg-bot {
  align-self: flex-start;
}
.ip-msg-bot .ip-msg-text {
  background: #f4f4f5;
  color: #303133;
}
.ip-msg-user {
  align-self: flex-end;
}
.ip-msg-user .ip-msg-text {
  background: #2e75b6;
  color: #fff;
}
.ip-quick {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.ip-quick-chip {
  cursor: pointer;
  font-size: 11px;
}
.ip-input {
  border-top: 1px solid #ebeef5;
  padding: 10px 14px;
  background: #fff;
}
.ip-input-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
  margin-top: 6px;
}
.ip-draft {
  padding: 0 14px 10px;
  border-top: 1px solid #ebeef5;
  background: #fff;
  max-height: calc(100vh - 240px);
  overflow-y: auto;
}
.ip-saved {
  padding: 16px 14px;
  border-top: 1px solid #ebeef5;
}

/* 移动端 drawer 内不需要 sticky, 高度铺满 */
:deep(.el-drawer__body) {
  padding: 0 !important;
  height: 100%;
}
</style>