<script setup lang="ts">
/**
 * Round 6-A Phase 3 — 面试官面板 · 素材草稿卡编辑
 * + R6-B Phase 6(spec §9): 显示 confidence_notes + verification 摘要 + save 前确认
 *
 * Props:  draftCard: InterviewDraftCard
 * Emits:
 *   - save(editedCard)      用户点确认写入素材库
 *   - continueAsking()      继续追问(返回 ASKING 状态)
 *   - discard()             丢弃草稿
 *   - switchGap()           换一个缺口
 *
 * 隐私边界(spec §9):
 *   - 不显示 prompt / raw response / source_span 明文
 *   - confidence_notes 来自 backend compute_confidence_notes(spec §7),只含 slot 名 + 短提示
 *   - verification 5 字段纯计数,不含 draft_bullets 原文
 *   - 弹窗 ElMessageBox.confirm 文案不含原文,只用计数 + 提示
 */
import { ref, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { InterviewDraftCard } from '../api'

const props = defineProps<{
  draftCard: InterviewDraftCard
  targetRole?: string
}>()

const emit = defineEmits<{
  save: [edited: InterviewDraftCard]
  continueAsking: []
  discard: []
  switchGap: []
}>()

// vue 3.5+ structuredClone 在 ts 里要求 reactive 对象先 toRaw — 提供兜底
function toRaw<T>(v: T): T {
  // 编辑场景只需要"快照"原始字段值,不依赖响应式追踪;直接 JSON 兜底也行
  try {
    return JSON.parse(JSON.stringify(v)) as T
  } catch {
    return v
  }
}

// 本地可编辑副本(避免直接改 props)
const editable = ref<InterviewDraftCard>(toRaw(props.draftCard))
const newBullet = ref('')

watch(
  () => props.draftCard,
  (next) => {
    editable.value = toRaw(next)
  },
)

// ----- R6-B Phase 6(spec §9): verification 摘要聚合 -----
// 5 字段全在 draftCard.verification 里(spec §7 + Phase 4 注入);老后端不返 → undefined → 不显示
const verification = computed(() => editable.value.verification ?? null)
const confidenceNotes = computed<string[]>(
  () => editable.value.confidence_notes ?? [],
)
// 是否有需要用户确认保存的高风险 claim(spec §9 save 前确认)
const needsSaveConfirm = computed(() => {
  const v = verification.value
  if (!v) return false
  return (v.unsupported_claims ?? 0) > 0 || (v.low_confidence_claims ?? 0) > 0
})

function addBullet() {
  const text = newBullet.value.trim()
  if (!text) return
  if (text.length > 200) {
    ElMessage.warning('单条 highlight 不能超过 200 字')
    return
  }
  editable.value.draft_bullets.push(text)
  newBullet.value = ''
}

function removeBullet(idx: number) {
  editable.value.draft_bullets.splice(idx, 1)
}

async function onSave() {
  if (editable.value.draft_bullets.length === 0) {
    ElMessage.warning('至少保留 1 条 highlight 才能写入素材库')
    return
  }
  if (!editable.value.title.trim()) {
    ElMessage.warning('请填写标题')
    return
  }

  // R6-B Phase 6(spec §9): verification 显示 unsupported / low_confidence > 0 时,
  // 弹确认提示(spec §7 — 不阻止保存,只让用户知情 + 确认);
  // 用计数 + 提示文案,不展示 bullet 原文,符合 spec §12 隐私边界
  if (needsSaveConfirm.value && verification.value) {
    const v = verification.value
    const lines: string[] = []
    if (v.unsupported_claims > 0) {
      lines.push(`• ${v.unsupported_claims} 条 highlight 在面试官回答里没找到来源证据,可能是系统推断或常识补充。`)
    }
    if (v.low_confidence_claims > 0) {
      lines.push(`• ${v.low_confidence_claims} 条 highlight 来自置信度较低的素材,请人工核对表述。`)
    }
    lines.push(`共 ${v.claims_total} 条 highlight,其中 ${v.claims_supported} 条已校验。`)
    const summary = lines.join('\n')
    try {
      await ElMessageBox.confirm(
        summary,
        '建议核对后再保存',
        {
          confirmButtonText: '仍然保存',
          cancelButtonText: '再改一下',
          type: 'warning',
        },
      )
    } catch {
      // 用户点取消 → 留在编辑界面,继续修改
      return
    }
  }

  emit('save', { ...editable.value })
}
</script>

<template>
  <div class="draft-card">
    <div class="dc-header">
      <span class="dc-title">素材草稿</span>
      <el-tag v-if="targetRole" size="small" type="info">{{ targetRole }}</el-tag>
    </div>

    <div class="dc-field">
      <label>标题 <span class="dc-required">*</span></label>
      <el-input v-model="editable.title" placeholder="例如:测试反馈整理流程" maxlength="80" show-word-limit />
    </div>

    <div class="dc-field">
      <label>职责</label>
      <el-input v-model="editable.responsibility" placeholder="我负责..." maxlength="200" />
    </div>

    <div class="dc-field">
      <label>结果 / 产出</label>
      <el-input
        v-model="editable.result"
        type="textarea"
        :rows="2"
        placeholder="最后带来了什么变化?"
        maxlength="500"
        show-word-limit
      />
    </div>

    <div class="dc-field">
      <label>Highlight bullets <span class="dc-required">*</span></label>
      <div class="dc-bullets">
        <div
          v-for="(b, i) in editable.draft_bullets"
          :key="i"
          class="dc-bullet-row"
        >
          <span class="dc-bullet-num">{{ i + 1 }}.</span>
          <span class="dc-bullet-text">{{ b }}</span>
          <el-button link type="danger" size="small" @click="removeBullet(i)">删除</el-button>
        </div>
        <div class="dc-bullet-add">
          <el-input
            v-model="newBullet"
            placeholder="新增一条 highlight(≤200 字)"
            maxlength="200"
            show-word-limit
            @keyup.enter="addBullet"
          />
          <el-button size="small" @click="addBullet">+ 添加</el-button>
        </div>
      </div>
    </div>

    <div v-if="editable.warnings?.length" class="dc-warnings">
      <div class="dc-warn-title">提示</div>
      <ul>
        <li v-for="(w, i) in editable.warnings" :key="i">{{ w }}</li>
      </ul>
    </div>

    <!-- R6-B Phase 6(spec §9): 显示 verification 摘要 + confidence_notes;
         5 字段聚合 + slot 名短提示, 不含 draft_bullets 原文 / source_span / prompt。
         verification / confidence_notes 来自 draft response(Phase 4 注入), 老后端不返则不显示。 -->
    <div v-if="confidenceNotes.length" class="dc-confidence-notes">
      <div class="dc-warn-title">置信度提示</div>
      <ul>
        <li v-for="(n, i) in confidenceNotes" :key="'cn-' + i">{{ n }}</li>
      </ul>
    </div>
    <div v-if="verification" class="dc-verification">
      <div class="dc-warn-title">事实核验摘要</div>
      <div class="dc-verify-row">
        <span class="dc-verify-lbl">共 {{ verification.claims_total }} 条 highlight</span>
        <el-tag size="small" type="success" effect="plain">已校验 {{ verification.claims_supported }}</el-tag>
        <el-tag
          v-if="verification.low_confidence_claims > 0"
          size="small"
          type="warning"
          effect="plain"
        >置信度偏低 {{ verification.low_confidence_claims }}</el-tag>
        <el-tag
          v-if="verification.unsupported_claims > 0"
          size="small"
          type="danger"
          effect="plain"
        >无来源 {{ verification.unsupported_claims }}</el-tag>
      </div>
      <div class="dc-verify-hint">
        保存前请人工核对 bullets 是否准确
      </div>
    </div>

    <div class="dc-actions">
      <el-button size="small" @click="emit('switchGap')">换一个缺口</el-button>
      <el-button size="small" @click="emit('continueAsking')">继续追问</el-button>
      <el-button size="small" type="danger" @click="emit('discard')">丢弃</el-button>
      <el-button size="small" type="primary" @click="onSave">确认写入素材库</el-button>
    </div>
  </div>
</template>

<style scoped>
.draft-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 8px 0;
}
.dc-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 4px;
  border-bottom: 1px dashed #e0e0e0;
}
.dc-title {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}
.dc-required {
  color: #f56c6c;
}
.dc-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.dc-field label {
  font-size: 12px;
  color: #606266;
  font-weight: 600;
}
.dc-bullets {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.dc-bullet-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background: #fafafa;
  border: 1px solid #f0f0f0;
  border-radius: 4px;
  font-size: 13px;
}
.dc-bullet-num {
  color: #909399;
  font-family: ui-monospace, monospace;
  flex-shrink: 0;
}
.dc-bullet-text {
  flex: 1;
  line-height: 1.5;
  word-break: break-word;
}
.dc-bullet-add {
  display: flex;
  gap: 6px;
  align-items: center;
}
.dc-warnings {
  padding: 6px 10px;
  background: #fdf6ec;
  border: 1px solid #faecd8;
  border-radius: 4px;
  font-size: 12px;
}
.dc-warn-title {
  font-weight: 600;
  color: #e6a23c;
  margin-bottom: 2px;
}
.dc-warnings ul {
  margin: 0;
  padding-left: 16px;
  color: #b88230;
  line-height: 1.6;
}
/* R6-B Phase 6(spec §9): 置信度提示 + 事实核验摘要 — 与 warnings 同区域,
   浅紫边框区分(避免和黄色 warning 混淆) */
.dc-confidence-notes {
  padding: 6px 10px;
  background: #f5f0fa;
  border: 1px solid #e0d2ee;
  border-radius: 4px;
  font-size: 12px;
}
.dc-confidence-notes ul {
  margin: 0;
  padding-left: 16px;
  color: #6a4c93;
  line-height: 1.6;
}
.dc-verification {
  padding: 6px 10px;
  background: #f5f5f7;
  border: 1px solid #e0e0e8;
  border-radius: 4px;
  font-size: 12px;
}
.dc-verify-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 4px;
}
.dc-verify-lbl {
  font-weight: 600;
  color: #303133;
  font-size: 12px;
}
.dc-verify-hint {
  color: #909399;
  font-size: 11px;
}
.dc-actions {
  display: flex;
  gap: 6px;
  justify-content: flex-end;
  flex-wrap: wrap;
  margin-top: 4px;
}
</style>