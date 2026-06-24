<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  materialsApi,
  resumeApi,
  downloadBlob,
  type MaterialSummary,
  type Role,
  type PreviewResponse,
  type Section,
} from './api'

const summary = ref<MaterialSummary | null>(null)
const roles = ref<Role[]>([])
const enabledRoles = ref<string[]>([])

// 表单
const selectedRole = ref<string>('tech_metric')
const customIntention = ref<string>('')

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
  loading.value = true
  try {
    previewData.value = await resumeApi.preview(
      selectedRole.value,
      customIntention.value.trim() || undefined
    )
    stage.value = 'preview'
    ElMessage.success('预览已生成,请 review 每个模块内容')
  } catch (e: any) {
    ElMessage.error(`预览失败: ${e?.response?.data?.detail ?? e?.message ?? '未知错误'}`)
  } finally {
    loading.value = false
  }
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
    const blob = await resumeApi.generate(
      selectedRole.value,
      customIntention.value.trim() || undefined
    )
    const roleName = currentRole.value?.name ?? '简历'
    const filename = `陈佳豪_${roleName}_${new Date().toISOString().slice(0, 10)}.docx`
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
                  <el-tag size="small" type="info">Round 1 · 大模型技术度量</el-tag>
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
</style>
