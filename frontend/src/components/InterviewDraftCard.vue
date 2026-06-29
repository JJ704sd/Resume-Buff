<script setup lang="ts">
/**
 * Round 6-A Phase 3 — 面试官面板 · 素材草稿卡编辑
 *
 * Props:  draftCard: InterviewDraftCard
 * Emits:
 *   - save(editedCard)      用户点确认写入素材库
 *   - continueAsking()      继续追问(返回 ASKING 状态)
 *   - discard()             丢弃草稿
 *   - switchGap()           换一个缺口
 */
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
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

function onSave() {
  if (editable.value.draft_bullets.length === 0) {
    ElMessage.warning('至少保留 1 条 highlight 才能写入素材库')
    return
  }
  if (!editable.value.title.trim()) {
    ElMessage.warning('请填写标题')
    return
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
.dc-actions {
  display: flex;
  gap: 6px;
  justify-content: flex-end;
  flex-wrap: wrap;
  margin-top: 4px;
}
</style>