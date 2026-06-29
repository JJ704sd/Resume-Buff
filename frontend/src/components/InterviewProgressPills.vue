<script setup lang="ts">
/**
 * Round 6-A Phase 3 — 面试官面板 · 已捕捉事实进度
 * 展示 slot 捕捉进度(7 个固定 slot: background / responsibility / action / method / difficulty / result / metric)
 * 不依赖 workflow 诊断类型(spec §3.3 边界)
 */
import { computed } from 'vue'
import type { InterviewProgress } from '../api'

const props = defineProps<{
  progress: InterviewProgress
}>()

const SLOT_LABELS: Record<string, string> = {
  background: '背景',
  responsibility: '职责',
  action: '动作',
  method: '方法',
  difficulty: '难点',
  result: '结果',
  metric: '数字',
}

const slots = computed(() => {
  const captured = props.progress.captured ?? {}
  // 固定顺序 + 容错(后端缺字段时全显 false)
  return Object.keys(SLOT_LABELS).map(slot => ({
    key: slot,
    label: SLOT_LABELS[slot] ?? slot,
    captured: Boolean(captured[slot]),
  }))
})

const capturedCount = computed(() => slots.value.filter(s => s.captured).length)
</script>

<template>
  <div class="progress-pills">
    <span class="pp-label">已捕捉 {{ capturedCount }} / {{ slots.length }}</span>
    <span
      v-for="s in slots"
      :key="s.key"
      class="pp-pill"
      :class="{ 'pp-done': s.captured, 'pp-pending': !s.captured }"
      :title="s.label + (s.captured ? ' · 已填' : ' · 待填')"
    >
      {{ s.label }}
    </span>
  </div>
</template>

<style scoped>
.progress-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
  padding: 4px 0;
}
.pp-label {
  font-size: 12px;
  color: #909399;
  margin-right: 4px;
}
.pp-pill {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  line-height: 1.5;
  white-space: nowrap;
  border: 1px solid;
}
.pp-done {
  background: #f0f9eb;
  color: #67c23a;
  border-color: #e1f3d8;
}
.pp-pending {
  background: #f4f4f5;
  color: #909399;
  border-color: #e9e9eb;
}
</style>