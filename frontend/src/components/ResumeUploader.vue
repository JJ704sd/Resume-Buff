<script setup lang="ts">
/**
 * 外部简历上传组件 (R3-G)
 *
 * 职责:
 *   - 用 Element Plus <el-upload drag> 接收 .docx/.pdf/.txt
 *   - 上传成功后调 /api/resume/parse-external,拿到 paragraphs
 *   - 通过 emit('parsed') 把全文本 + 段落列表给父组件
 *   - 显示已上传文件名 / 段落数 / 删除按钮
 *
 * 设计:
 *   - 中文 UI 文案
 *   - 失败用 ElMessage.error 展示后端 detail
 *   - 上传过程显示 loading
 *   - 父组件只需关心 @parsed 事件,内部状态全封闭
 */
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { resumeApi, type ParsedResume } from '../api'

const emit = defineEmits<{
  (e: 'parsed', payload: {
    filename: string
    text: string           // 拼接所有 paragraph.text 的全文
    paragraphs: ParsedResume['paragraphs']
  }): void
}>()

const uploaded = ref<ParsedResume | null>(null)
const loading = ref(false)

// 已上传的文件大小(格式化展示)
const fileSizeText = computed(() => {
  if (!uploaded.value) return ''
  const b = uploaded.value.size_bytes
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`
  return `${(b / 1024 / 1024).toFixed(2)} MB`
})

// 已上传文件的段落数(仅非空)
const paraCount = computed(() => {
  if (!uploaded.value) return 0
  return uploaded.value.paragraphs.filter(p => p.text && p.text.trim()).length
})

async function handleUpload(option: { file: File }) {
  const file = option.file
  if (!file) {
    ElMessage.error('未收到文件')
    return
  }
  loading.value = true
  try {
    const result = await resumeApi.parseExternal(file)
    uploaded.value = result
    // 拼成全文给父组件(去掉空行,避免污染 JD 匹配搜索)
    const text = result.paragraphs
      .map(p => p.text)
      .filter(t => t && t.trim())
      .join('\n')
    emit('parsed', {
      filename: result.filename,
      text,
      paragraphs: result.paragraphs,
    })
    ElMessage.success(
      `已解析 ${result.filename}(${fileSizeText.value},${paraCount.value} 段)`
    )
  } catch (e: any) {
    const detail = e?.response?.data?.detail ?? e?.message ?? '未知错误'
    ElMessage.error(`简历解析失败: ${detail}`)
    uploaded.value = null
  } finally {
    loading.value = false
  }
}

function handleRemove() {
  uploaded.value = null
  // 通知父组件清除(通过同一个 emit 事件,payload 为空文本)
  emit('parsed', { filename: '', text: '', paragraphs: [] })
}

function handleBeforeUpload(file: File): boolean {
  // 客户端预校验后缀(后端会再校验一次)
  const name = file.name.toLowerCase()
  if (!name.endsWith('.docx') && !name.endsWith('.pdf') && !name.endsWith('.txt')) {
    ElMessage.warning('仅支持 .docx / .pdf / .txt 文件')
    return false
  }
  if (file.size > 5 * 1024 * 1024) {
    ElMessage.warning('文件不能超过 5 MB')
    return false
  }
  return true  // 继续上传
}
</script>

<template>
  <div class="resume-uploader">
    <!-- 未上传:显示拖拽区 -->
    <el-upload
      v-if="!uploaded"
      drag
      action="#"
      :auto-upload="true"
      :http-request="handleUpload"
      :before-upload="handleBeforeUpload"
      :show-file-list="false"
      accept=".docx,.pdf,.txt"
      :loading="loading"
    >
      <div class="upload-icon">
        <el-icon :size="40" color="#909399">
          <svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg">
            <path fill="currentColor" d="M480 480V128a32 32 0 0 1 64 0v352h352a32 32 0 1 1 0 64H544v352a32 32 0 1 1-64 0V544H128a32 32 0 1 1 0-64h352z"/>
          </svg>
        </el-icon>
      </div>
      <div class="upload-text">将简历拖到此处,或<em>点击上传</em></div>
      <div class="upload-hint">支持 .docx / .pdf / .txt · 不超过 5 MB · 文件不会保存到本地</div>
    </el-upload>

    <!-- 已上传:展示卡片 + 删除按钮 -->
    <div v-else class="uploaded-card">
      <div class="info">
        <div class="filename-row">
          <el-icon class="file-icon" :size="20" color="#67c23a">
            <svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg">
              <path fill="currentColor" d="M704 192h-288A96 96 0 0 0 320 288v448a96 96 0 0 0 96 96h288a96 96 0 0 0 96-96V288a96 96 0 0 0-96-96z m-32 416a32 32 0 1 1 0-64 32 32 0 0 1 0 64z m-320-64a32 32 0 0 1-64 0V288a96 96 0 0 1 96-96h288a96 96 0 0 1 96 96v32a32 32 0 0 1-64 0v-32a32 32 0 0 0-32-32h-288a32 32 0 0 0-32 32v256z"/>
            </svg>
          </el-icon>
          <span class="filename">{{ uploaded.filename }}</span>
          <el-tag size="small" type="success" effect="plain">已解析</el-tag>
        </div>
        <div class="meta">
          <span>{{ fileSizeText }}</span>
          <span class="sep">·</span>
          <span>{{ paraCount }} 段</span>
          <span v-if="uploaded.page_count" class="sep">·</span>
          <span v-if="uploaded.page_count">{{ uploaded.page_count }} 页</span>
          <span class="sep">·</span>
          <span>{{ uploaded.note }}</span>
        </div>
      </div>
      <el-button size="small" plain @click="handleRemove">删除</el-button>
    </div>
  </div>
</template>

<style scoped>
.resume-uploader {
  width: 100%;
}

.upload-icon {
  display: flex;
  justify-content: center;
  margin-bottom: 8px;
}

.upload-text {
  color: #303133;
  font-size: 14px;
  margin-bottom: 4px;
}
.upload-text em {
  color: #2e75b6;
  font-style: normal;
  font-weight: 600;
}

.upload-hint {
  color: #909399;
  font-size: 12px;
  line-height: 1.6;
}

/* 已上传卡片 */
.uploaded-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid #e1f3d8;
  background: #f0f9eb;
  border-radius: 6px;
}

.info {
  flex: 1;
  min-width: 0;
}

.filename-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.file-icon {
  flex-shrink: 0;
}

.filename {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  word-break: break-all;
}

.meta {
  font-size: 12px;
  color: #909399;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}

.sep {
  color: #dcdfe6;
}
</style>