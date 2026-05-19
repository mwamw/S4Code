import type { AppState, TranscriptCard, TranscriptCardKind } from './AppStateStore'
import type { S4BridgeEvent } from '../types/bridge'

let nextCardId = 0

function newCard(
  kind: TranscriptCardKind,
  title: string,
  body: string,
  status?: string,
  metadata?: Record<string, unknown>,
): TranscriptCard {
  nextCardId += 1
  return {
    id: `card-${nextCardId}`,
    kind,
    title,
    body,
    status,
    metadata,
  }
}

function withCommittedCards(state: AppState, cards: TranscriptCard[]): AppState {
  return {
    ...state,
    transcript: {
      ...state.transcript,
      committedCards: cards,
      cards,
    },
  }
}

export function getVisibleTranscriptCards(transcript: AppState['transcript']): TranscriptCard[] {
  return [
    ...(transcript.committedCards || transcript.cards || []),
    ...[
      transcript.liveRoundCard,
      transcript.liveThinkingCard,
      transcript.liveAssistantCard,
      ...Object.values(transcript.liveToolCards || {}),
    ].filter((card): card is TranscriptCard => Boolean(card)),
  ]
}

export function appendCard(
  state: AppState,
  kind: TranscriptCardKind,
  title: string,
  body: string,
  status?: string,
  metadata?: Record<string, unknown>,
): AppState {
  return withCommittedCards(
    state,
    [...(state.transcript.committedCards || state.transcript.cards || []), newCard(kind, title, body, status, metadata)],
  )
}

function updateCommittedCard(
  state: AppState,
  cardId: string | undefined,
  updater: (card: TranscriptCard) => TranscriptCard,
): AppState {
  if (!cardId) {
    return state
  }
  const cards = (state.transcript.committedCards || state.transcript.cards || []).map(card => {
    if (card.id !== cardId) {
      return card
    }
    return updater(card)
  })
  return withCommittedCards(state, cards)
}

function updateTranscriptCard(
  state: AppState,
  cardId: string | undefined,
  updater: (card: TranscriptCard) => TranscriptCard,
): AppState {
  if (!cardId) {
    return state
  }
  let changed = false
  const committedCards = (state.transcript.committedCards || state.transcript.cards || []).map(card => {
    if (card.id !== cardId) {
      return card
    }
    changed = true
    return updater(card)
  })
  const updateLiveCard = (card: TranscriptCard | undefined): TranscriptCard | undefined => {
    if (!card || card.id !== cardId) {
      return card
    }
    changed = true
    return updater(card)
  }
  const liveToolCards: Record<string, TranscriptCard> = {}
  let toolCardsChanged = false
  for (const [toolId, card] of Object.entries(state.transcript.liveToolCards || {})) {
    if (card.id === cardId) {
      changed = true
      toolCardsChanged = true
      liveToolCards[toolId] = updater(card)
    } else {
      liveToolCards[toolId] = card
    }
  }
  const liveRoundCard = updateLiveCard(state.transcript.liveRoundCard)
  const liveThinkingCard = updateLiveCard(state.transcript.liveThinkingCard)
  const liveAssistantCard = updateLiveCard(state.transcript.liveAssistantCard)
  if (!changed) {
    return state
  }
  return {
    ...state,
    transcript: {
      ...state.transcript,
      committedCards,
      cards: committedCards,
      liveRoundCard,
      liveThinkingCard,
      liveAssistantCard,
      liveToolCards: toolCardsChanged ? liveToolCards : state.transcript.liveToolCards,
    },
  }
}

function summarizeScalar(value: unknown, maxChars = 180): string {
  if (value === null || value === undefined) {
    return ''
  }
  const text = typeof value === 'string'
    ? value.replace(/\s+/g, ' ').trim()
    : JSON.stringify(value)
  if (!text) {
    return ''
  }
  if (text.length <= maxChars) {
    return text
  }
  return `${text.slice(0, maxChars).trimEnd()}...`
}

function nextSyntheticToolId(prefix: 'tool-call' | 'tool-result'): string {
  return `${prefix}-${nextCardId + 1}`
}

function nowSeconds(): number {
  return Date.now() / 1000
}

function numberValue(value: unknown, fallback = 0): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function formatDuration(seconds: number): string {
  const safeSeconds = Math.max(Number(seconds) || 0, 0)
  if (safeSeconds < 60) {
    return `${safeSeconds.toFixed(1)}s`
  }
  const minutes = Math.floor(safeSeconds / 60)
  const remainder = safeSeconds % 60
  if (minutes < 60) {
    return `${minutes}m ${remainder.toFixed(1).padStart(4, '0')}s`
  }
  const hours = Math.floor(minutes / 60)
  const minuteRemainder = minutes % 60
  return `${hours}h ${String(minuteRemainder).padStart(2, '0')}m ${remainder.toFixed(1).padStart(4, '0')}s`
}

function formatMetricInt(value: unknown): string {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? Math.trunc(parsed).toLocaleString('en-US') : '?'
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map(item => String(item).trim()).filter(Boolean)
    : []
}

function mergeMetrics(current: Record<string, unknown> | undefined, incoming: Record<string, unknown> | undefined): Record<string, unknown> {
  const merged: Record<string, unknown> = { ...(current || {}) }
  for (const [key, value] of Object.entries(incoming || {})) {
    if (value === null || value === undefined) {
      continue
    }
    if (key === 'files_changed' || key === 'tools_used') {
      merged[key] = Array.from(new Set([...stringList(merged[key]), ...stringList(value)])).sort()
      continue
    }
    merged[key] = value
  }
  return merged
}

function metricsFromRoundCard(card: TranscriptCard | undefined): Record<string, unknown> {
  const metrics = card?.metadata?.metrics
  return metrics && typeof metrics === 'object' && !Array.isArray(metrics)
    ? metrics as Record<string, unknown>
    : {}
}

function formatRoundMetricsLine(metrics: Record<string, unknown>, outcome: string): string {
  const items: string[] = []
  const toolCalls = Math.trunc(numberValue(metrics.tool_calls))
  const runningTools = Math.trunc(numberValue(metrics.running_tools))
  const toolErrors = Math.trunc(numberValue(metrics.tool_errors))
  if (toolCalls > 0) {
    items.push(outcome === 'running' && runningTools > 0 ? `Tools ${toolCalls} (${runningTools} running)` : `Tools ${toolCalls}`)
  }
  const modelSeconds = numberValue(metrics.llm_duration_ms) / 1000
  if (modelSeconds > 0) {
    items.push(`Model ${formatDuration(modelSeconds)}`)
  }
  const toolSeconds = Math.max(numberValue(metrics.tool_duration_ms) / 1000, numberValue(metrics.local_tool_seconds))
  if (toolSeconds > 0) {
    items.push(`Tool ${formatDuration(toolSeconds)}`)
  }
  const filesChanged = stringList(metrics.files_changed)
  if (filesChanged.length > 0) {
    items.push(`Files ${filesChanged.length}`)
  }
  if (toolErrors > 0) {
    items.push(`Errors ${toolErrors}`)
  }
  if (outcome === 'pending') {
    items.push('Waiting')
  } else if (outcome === 'error') {
    items.push('Errored')
  } else if (outcome === 'interrupted') {
    items.push('Interrupted')
  }
  return items.join(' | ')
}

function formatRoundDetails(metrics: Record<string, unknown>): string[] {
  const lines: string[] = []
  const toolsUsed = stringList(metrics.tools_used)
  if (toolsUsed.length > 0) {
    lines.push(`Used: ${toolsUsed.slice(0, 6).join(', ')}`)
  }
  const filesChanged = stringList(metrics.files_changed)
  if (filesChanged.length > 0) {
    lines.push(`Changed: ${filesChanged.slice(0, 5).join(', ')}`)
  }
  return lines
}

function formatActiveRoundBody(startedAt: number, metrics: Record<string, unknown>, now = nowSeconds()): string {
  const lines = [`Elapsed: ${formatDuration(now - startedAt)}`]
  const metricsLine = formatRoundMetricsLine(metrics, 'running')
  if (metricsLine) {
    lines.push(metricsLine)
  }
  lines.push(...formatRoundDetails(metrics))
  return lines.join('\n')
}

function formatCompletedRoundBody(
  startedAt: number,
  finishedAt: number,
  metrics: Record<string, unknown>,
  outcome = 'completed',
): string {
  const label = {
    completed: 'Completed in',
    pending: 'Paused after',
    error: 'Errored after',
    interrupted: 'Interrupted in',
  }[outcome] || 'Completed in'
  const lines = [`${label} ${formatDuration(finishedAt - startedAt)}`]
  const metricsLine = formatRoundMetricsLine(metrics, outcome)
  if (metricsLine) {
    lines.push(metricsLine)
  }
  lines.push(...formatRoundDetails(metrics))
  return lines.join('\n')
}

function formatMessageMetricsFooter(metrics: Record<string, unknown>): string {
  const items: string[] = []
  if (metrics.context_used_tokens !== undefined || metrics.context_max_tokens !== undefined) {
    items.push(`Ctx ${metrics.context_used_tokens !== undefined ? formatMetricInt(metrics.context_used_tokens) : '?'}/${metrics.context_max_tokens !== undefined ? formatMetricInt(metrics.context_max_tokens) : '?'}`)
  }
  const inputTokens = Math.trunc(numberValue(metrics.input_tokens))
  const outputTokens = Math.trunc(numberValue(metrics.output_tokens))
  const totalTokens = Math.trunc(numberValue(metrics.total_tokens))
  if (inputTokens > 0) {
    items.push(`In ${formatMetricInt(inputTokens)}`)
  }
  if (outputTokens > 0) {
    items.push(`Out ${formatMetricInt(outputTokens)}`)
  }
  if (totalTokens > 0) {
    items.push(`Total ${formatMetricInt(totalTokens)}`)
  }
  const promptTotal = Math.trunc(numberValue(metrics.prompt_tokens_total))
  const cacheTokens = Math.max(
    Math.trunc(numberValue(metrics.prompt_tokens_cached)),
    Math.trunc(numberValue(metrics.cached_input_tokens)),
  )
  if (cacheTokens > 0) {
    items.push(promptTotal > 0 ? `Cache ${formatMetricInt(cacheTokens)}/${formatMetricInt(promptTotal)}` : `Cache ${formatMetricInt(cacheTokens)}`)
  }
  if (metrics.estimated_cost_usd !== undefined && metrics.estimated_cost_usd !== null) {
    const cost = Number(metrics.estimated_cost_usd)
    if (Number.isFinite(cost)) {
      items.push(`Cost $${cost.toFixed(4)}`)
    }
  }
  return items.join('  ·  ')
}

function summarizeToolArgs(toolArgs: unknown): string {
  if (!toolArgs || typeof toolArgs !== 'object') {
    return summarizeScalar(toolArgs)
  }
  const record = toolArgs as Record<string, unknown>
  const priorityKeys = [
    'file_path',
    'path',
    'notebook_path',
    'directory',
    'cwd',
    'workspace_root',
    'command',
    'agent_id',
    'team_id',
    'recipient_id',
    'server',
    'uri',
    'name',
    'action',
    'description',
  ]
  const lines: string[] = []
  for (const key of priorityKeys) {
    const value = record[key]
    if (value === null || value === undefined || value === '' || value === false) {
      continue
    }
    if (Array.isArray(value) && value.length === 0) {
      continue
    }
    if (typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === 0) {
      continue
    }
    lines.push(`${key}: ${summarizeScalar(value, 140)}`)
    if (lines.length >= 4) {
      break
    }
  }
  if (lines.length > 0) {
    const hidden = Math.max(Object.keys(record).length - lines.length, 0)
    if (hidden > 0) {
      lines.push(`... ${hidden} more field(s) hidden`)
    }
    return lines.join('\n')
  }
  return summarizeScalar(record, 180)
}

function formatToolResultBody(event: S4BridgeEvent): string {
  const structuredData = (event.structured_data && typeof event.structured_data === 'object')
    ? event.structured_data as Record<string, unknown>
    : null
  const backgroundTask = structuredData?.background_task && typeof structuredData.background_task === 'object'
    ? structuredData.background_task as Record<string, unknown>
    : null
  const taskSource = backgroundTask || structuredData
  const taskId = String(taskSource?.task_id || '').trim()
  const taskStatus = String(taskSource?.status || '').trim().toLowerCase()
  if (taskId && ['running', 'queued', 'waiting'].includes(taskStatus)) {
    const lines = [`Started background task \`${taskId}\`.`]
    const description = String(taskSource?.description || '').trim()
    const command = String(taskSource?.command || '').replace(/\n/g, ' ').trim()
    if (description) {
      lines.push(`Purpose: ${summarizeScalar(description, 140)}`)
    } else if (command) {
      lines.push(`Command: ${summarizeScalar(command, 140)}`)
    }
    lines.push(`Use \`/task output ${taskId}\` to stream logs.`)
    lines.push(`Use \`/task stop ${taskId}\` to stop it.`)
    return lines.join('\n')
  }

  const text = String(event.content || '').trim()
  if (!text) {
    return 'Completed with no textual output.'
  }
  const lines = text
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
  const firstLine = lines[0] || text
  const summary = summarizeScalar(firstLine, 180)
  const hiddenLines = Math.max(lines.length - 1, 0)
  return hiddenLines > 0 ? `${summary}\n... ${hiddenLines} more line(s) hidden` : summary
}

function extractToolResultMetadata(event: S4BridgeEvent): Record<string, unknown> {
  const metadata: Record<string, unknown> = {}
  const structuredData = (event.structured_data && typeof event.structured_data === 'object')
    ? event.structured_data as Record<string, unknown>
    : null
  const diffPayload = structuredData?.diff && typeof structuredData.diff === 'object'
    ? structuredData.diff as Record<string, unknown>
    : null
  const unified = String(diffPayload?.unified || '').trim()
  if (unified) {
    metadata.diff = {
      unified,
      file_path: String(diffPayload?.file_path || structuredData?.file_path || '').trim(),
      relative_path: String(diffPayload?.relative_path || '').trim(),
      created: Boolean(diffPayload?.created),
      source: String(diffPayload?.source || '').trim(),
    }
  }
  const resultMetadata = (event.result_metadata && typeof event.result_metadata === 'object')
    ? event.result_metadata as Record<string, unknown>
    : null
  if (resultMetadata && Object.keys(resultMetadata).length > 0) {
    metadata.result_metadata = { ...resultMetadata }
  }
  const backgroundTask = structuredData?.background_task && typeof structuredData.background_task === 'object'
    ? structuredData.background_task as Record<string, unknown>
    : null
  const taskSource = backgroundTask || structuredData
  const taskId = String(taskSource?.task_id || '').trim()
  if (taskId) {
    metadata.background_task = {
      task_id: taskId,
      status: String(taskSource?.status || '').trim(),
      command: String(taskSource?.command || '').trim(),
    }
  }
  const errorType = String(event.error_type || '').trim()
  if (errorType) {
    metadata.error_type = errorType
  }
  const resultStatus = String(event.status || '').trim()
  if (resultStatus) {
    metadata.result_status = resultStatus
  }
  return metadata
}

function resolveToolCardStatus(event: S4BridgeEvent): string {
  const status = String(event.status || '').trim()
  if (status === 'error') {
    return 'error'
  }
  if (status === 'needs_confirmation') {
    return 'pending'
  }
  return 'done'
}

function formatRoundOutcome(metrics: Record<string, unknown> | undefined): string {
  const toolsUsed = Array.isArray(metrics?.tools_used) ? metrics?.tools_used.join(', ') : 'none'
  const filesChanged = Array.isArray(metrics?.files_changed) ? metrics?.files_changed.join(', ') : 'none'
  const context = typeof metrics?.context_usage_percent === 'string' ? metrics.context_usage_percent : null
  const cache = typeof metrics?.cache_hit_ratio === 'number' ? `${Math.round(metrics.cache_hit_ratio * 100)}%` : null
  const lines = [
    `Tools used: ${toolsUsed}`,
    `Files changed: ${filesChanged}`,
  ]
  if (context) {
    lines.push(`Context used: ${context}`)
  }
  if (cache) {
    lines.push(`Cache hit rate: ${cache}`)
  }
  return lines.join('\n')
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function formatInterruptionBody(event: S4BridgeEvent): { title: string; body: string; pending: Record<string, unknown> } {
  const payload = asRecord(event.payload)
  const metadata = asRecord(payload.metadata)
  const interactionType = String(metadata.interaction_type || 'confirmation')

  if (interactionType === 'ask_user_question') {
    const lines = [
      'The agent needs your answer before it can continue.',
      '',
    ]
    const message = String(payload.message || event.content || '').trim()
    if (message) {
      lines.push(message, '')
    }
    const questions = Array.isArray(metadata.questions) ? metadata.questions : []
    if (questions.length > 0) {
      lines.push('Questions:')
      questions.forEach((rawQuestion, index) => {
        const item = asRecord(rawQuestion)
        const header = String(item.header || `Question ${index + 1}`).trim()
        const question = String(item.question || '').trim()
        lines.push(`${index + 1}. ${header}`)
        if (question) {
          lines.push(`   ${question}`)
        }
        const options = Array.isArray(item.options) ? item.options : []
        for (const rawOption of options) {
          const option = asRecord(rawOption)
          const label = String(option.label || '').trim()
          const description = String(option.description || '').trim()
          lines.push(`   - ${label || 'option'}${description ? `: ${description}` : ''}`)
        }
      })
      lines.push('')
    }
    const source = String(metadata.source || '').trim()
    if (source) {
      lines.push(`Source: ${source}`)
    }
    lines.push('Next step:')
    lines.push('- Use `/answer <text>` to continue.')
    lines.push('- Use `/deny [reason]` to decline.')
    return {
      title: 'Ask User Question',
      body: lines.join('\n').trim(),
      pending: {
        active: true,
        title: 'Answer needed',
        interaction_type: interactionType,
        remember_supported: false,
      },
    }
  }

  if (interactionType === 'enter_plan_mode') {
    const lines = ['The agent wants to switch into planning mode before making changes.']
    const reason = String(metadata.reason || '').trim()
    if (reason) {
      lines.push(`Why this helps: ${reason}`)
    }
    const allowedActions = Array.isArray(metadata.allowedActions) ? metadata.allowedActions : []
    if (allowedActions.length > 0) {
      lines.push('What it wants to do:')
      for (const item of allowedActions) {
        lines.push(`- ${summarizeScalar(item, 120)}`)
      }
    }
    lines.push('Next step:')
    lines.push('- Use `/confirm` to enter plan mode.')
    lines.push('- Use `/deny [reason]` to refuse.')
    return {
      title: 'Enter Plan Mode Request',
      body: lines.join('\n'),
      pending: {
        active: true,
        title: 'Mode change pending',
        interaction_type: interactionType,
        risk_level: 'medium',
      },
    }
  }

  if (interactionType === 'exit_plan_mode') {
    const lines = ['The agent is ready to leave planning mode and continue execution.']
    const allowedPrompts = Array.isArray(metadata.allowedPrompts) ? metadata.allowedPrompts : []
    if (allowedPrompts.length > 0) {
      lines.push('Requested permission categories:')
      for (const rawPrompt of allowedPrompts) {
        const item = asRecord(rawPrompt)
        const tool = String(item.tool || 'tool').trim()
        const prompt = String(item.prompt || '').trim()
        lines.push(prompt ? `- ${tool}: ${prompt}` : `- ${tool}`)
      }
    }
    lines.push('Next step:')
    lines.push('- Use `/confirm` to leave plan mode.')
    lines.push('- Use `/deny [reason]` to stay in plan mode.')
    return {
      title: 'Exit Plan Mode Request',
      body: lines.join('\n'),
      pending: {
        active: true,
        title: 'Mode change pending',
        interaction_type: interactionType,
        risk_level: 'medium',
      },
    }
  }

  const toolName = String(payload.tool_name || event.tool_name || '').trim()
  const lines = ['The agent is waiting for your approval before it continues.']
  const content = String(event.content || payload.message || '').trim()
  if (content) {
    lines.push('', content)
  }
  if (toolName) {
    lines.push(`Tool: ${toolName}`)
  }
  const reason = String(metadata.reason || '').trim()
  if (reason) {
    lines.push(`Why this needs approval: ${reason}`)
  }
  const toolArgs = asRecord(payload.tool_args)
  if (Object.keys(toolArgs).length > 0) {
    lines.push('Requested arguments:')
    lines.push(summarizeToolArgs(toolArgs))
  }
  lines.push('Next step:')
  lines.push('- Use `/confirm [note]` to continue.')
  lines.push('- Use `/confirm remember` to allow a matching action for this session.')
  lines.push('- Use `/deny [reason]` to cancel.')
  return {
    title: 'Pending Confirmation',
    body: lines.join('\n'),
    pending: {
      active: true,
      title: 'Approval required',
      interaction_type: interactionType,
      tool_name: toolName || null,
      reason: reason || null,
      remember_supported: true,
    },
  }
}

function formatRuntimeSnapshot(snapshot: unknown): string {
  if (!snapshot || typeof snapshot !== 'object') {
    return 'Runtime snapshot unavailable.'
  }
  const payload = snapshot as Record<string, unknown>
  const session = asRecord(payload.session)
  const worktree = asRecord(payload.worktree)
  const activeWorktree = asRecord(worktree.active)
  const agents = Array.isArray(payload.agents) ? payload.agents : []
  const tasks = Array.isArray(payload.tasks) ? payload.tasks : []
  const backgroundTasks = Array.isArray(payload.background_tasks) ? payload.background_tasks : []
  const context = asRecord(payload.context)
  const lines = [
    `Updated: ${payload.generated_at || '-'}`,
    `Session: ${session.session_id || '-'} | checkpoints=${session.checkpoints || 0}`,
    '',
    'Worktree:',
  ]
  lines.push(
    Object.keys(activeWorktree).length > 0
      ? `- ${activeWorktree.branch || '-'} @ ${activeWorktree.path || '-'}`
      : '- none',
  )
  lines.push('', 'Agents:')
  if (agents.length > 0) {
    for (const item of agents.slice(0, 6)) {
      const agent = asRecord(item)
      lines.push(`- ${agent.agent_id || '-'} | ${agent.status || '-'} | ${agent.name || '-'}`)
    }
  } else {
    lines.push('- none')
  }
  lines.push('', 'Tasks:')
  if (tasks.length > 0 || backgroundTasks.length > 0) {
    for (const item of tasks.slice(0, 6)) {
      const task = asRecord(item)
      lines.push(`- ${task.task_id || '-'} | ${task.status || '-'} | ${task.title || '-'}`)
    }
    for (const item of backgroundTasks.slice(0, 6)) {
      const task = asRecord(item)
      const command = summarizeScalar(String(task.command || '').replace(/\n/g, ' '), 100) || String(task.cwd || '-')
      const duration = Number(task.duration_seconds)
      const durationText = Number.isFinite(duration) ? ` | ${duration.toFixed(1)}s` : ''
      lines.push(`- ${task.task_id || '-'} | ${task.status || '-'} | rc=${task.return_code}${durationText} | ${command}`)
      const stdoutTail = String(task.stdout_tail || '').trim()
      const stderrTail = String(task.stderr_tail || '').trim()
      if (stdoutTail) {
        lines.push(`  stdout: ${summarizeScalar(stdoutTail, 160)}`)
      }
      if (stderrTail) {
        lines.push(`  stderr: ${summarizeScalar(stderrTail, 160)}`)
      }
    }
  } else {
    lines.push('- none')
  }
  if (Object.keys(context).length > 0) {
    lines.push(
      '',
      `Context: ${context.usage_percent || '-'} (${context.used_tokens ?? '?'} / ${context.max_tokens ?? '?'} used, ${context.remaining_tokens ?? '?'} remaining)`,
    )
  }
  return lines.join('\n')
}

function checkpointAnnotation(checkpoint: Record<string, unknown>): Record<string, unknown> {
  return {
    checkpoint_id: String(checkpoint.checkpoint_id || '').trim(),
    label: String(checkpoint.label || '').trim(),
    reason: String(checkpoint.reason || '').trim(),
    history_messages: checkpoint.history_messages || 0,
    created_at: String(checkpoint.created_at || '').trim(),
  }
}

function canAnnotateCheckpoint(card: TranscriptCard): boolean {
  return !['separator', 'round', 'runtime'].includes(card.kind)
}

function findCheckpointTarget(cards: TranscriptCard[], checkpoint: Record<string, unknown>): TranscriptCard | undefined {
  const reason = String(checkpoint.reason || '')
  let preferredKinds: string[]
  if (reason === 'before_prompt') {
    preferredKinds = ['user']
  } else if (reason === 'interruption') {
    preferredKinds = ['warning', 'assistant', 'user']
  } else if (reason === 'after_prompt') {
    preferredKinds = ['assistant', 'warning', 'error', 'user']
  } else {
    preferredKinds = ['assistant', 'warning', 'system', 'user', 'error', 'tool']
  }
  for (const card of [...cards].reverse()) {
    if (preferredKinds.includes(card.kind) && canAnnotateCheckpoint(card)) {
      return card
    }
  }
  return [...cards].reverse().find(canAnnotateCheckpoint)
}

function addCheckpointToCard(card: TranscriptCard, checkpoint: Record<string, unknown>): TranscriptCard {
  const current = Array.isArray(card.metadata?.checkpoints) ? card.metadata?.checkpoints : []
  const checkpointId = String(checkpoint.checkpoint_id || '')
  if (checkpointId && current.some(item => asRecord(item).checkpoint_id === checkpointId)) {
    return card
  }
  return {
    ...card,
    metadata: {
      ...(card.metadata || {}),
      checkpoints: [...current, { ...checkpoint }],
    },
  }
}

function applyCheckpoint(state: AppState, checkpoint: Record<string, unknown>): AppState {
  const target = findCheckpointTarget(getVisibleTranscriptCards(state.transcript), checkpoint)
  return target ? updateTranscriptCard(state, target.id, card => addCheckpointToCard(card, checkpoint)) : state
}

function maybeAppendSummaryCards(state: AppState): AppState {
  const metrics = state.transcript.lastRoundMetrics
  let nextState = appendCard(
    state,
    'system',
    'Round Outcome',
    formatRoundOutcome(metrics),
    'done',
    { outcome_summary: true },
  )

  const filesChanged = Array.isArray(metrics?.files_changed)
    ? metrics.files_changed.filter(item => typeof item === 'string' && item.trim())
    : []
  if (filesChanged.length > 0) {
    nextState = appendCard(
      nextState,
      'system',
      'Changed Files',
      filesChanged.map(item => `- ${item}`).join('\n'),
      'done',
      { changed_files: filesChanged },
    )
  }

  const toolsUsed = Array.isArray(metrics?.tools_used)
    ? metrics.tools_used.filter(item => typeof item === 'string' && item.trim())
    : []
  if (toolsUsed.some(item => String(item).toLowerCase() === 'bash')) {
    nextState = appendCard(
      nextState,
      'system',
      'Verification',
      'This round ran command-line tooling. Inspect task output or command results for verification details.',
      'done',
      { verification: true },
    )
  }
  const activeTasks = Object.values(nextState.tasks.items || {})
    .filter(task => ['started', 'running', 'queued', 'waiting'].includes(String(task.status || '').toLowerCase()))
    .map(task => `${task.id}: ${task.title}`)
  const pendingTitle = nextState.permissions.pending?.active
    ? nextState.permissions.pending.title || 'Pending interaction'
    : ''
  if (activeTasks.length > 0 || pendingTitle) {
    const lines = [
      ...activeTasks.map(item => `- Task ${item}`),
      ...(pendingTitle ? [`- ${pendingTitle}`] : []),
    ]
    nextState = appendCard(
      nextState,
      'system',
      'Pending Work',
      lines.join('\n'),
      'waiting',
      { pending_work: true },
    )
  }
  return nextState
}

export function appendStreamDelta(
  state: AppState,
  deltas: { thinking?: string; assistant?: string },
): AppState {
  const thinking = deltas.thinking || ''
  const assistant = deltas.assistant || ''
  if (!thinking && !assistant) {
    return state
  }
  const roundMetadata = state.runtime.currentRound ? { round: state.runtime.currentRound } : undefined

  const liveThinkingCard = thinking
    ? {
        ...(state.transcript.liveThinkingCard || newCard('thinking', 'Model Thinking', '', 'streaming', roundMetadata)),
        body: `${state.transcript.liveThinkingCard?.body || ''}${thinking}`,
        status: 'streaming',
      }
    : state.transcript.liveThinkingCard
  const liveAssistantCard = assistant
    ? {
        ...(state.transcript.liveAssistantCard || newCard('assistant', 'Model Response', '', 'streaming', roundMetadata)),
        body: `${state.transcript.liveAssistantCard?.body || ''}${assistant}`,
        status: 'streaming',
      }
    : state.transcript.liveAssistantCard

  return {
    ...state,
    runtime: {
      ...state.runtime,
      streaming: true,
    },
    transcript: {
      ...state.transcript,
      liveThinkingCard,
      liveAssistantCard,
      streamFlushAt: Date.now(),
    },
  }
}

function hasLiveTranscript(state: AppState): boolean {
  return Boolean(
    state.transcript.liveRoundCard
    || state.transcript.liveThinkingCard
    || state.transcript.liveAssistantCard
    || Object.keys(state.transcript.liveToolCards || {}).length > 0,
  )
}

function liveCardsForCommit(
  state: AppState,
  options: {
    finalContent?: string
    roundBody?: string
    roundStatus?: string
    roundOutcome?: string
  } = {},
): TranscriptCard[] {
  const result: TranscriptCard[] = []
  const roundMetrics = mergeMetrics(metricsFromRoundCard(state.transcript.liveRoundCard), state.transcript.lastRoundMetrics)
  const assistantFooter = formatMessageMetricsFooter(roundMetrics)
  if (state.transcript.liveRoundCard) {
    const startedAt = numberValue(state.transcript.liveRoundCard.metadata?.started_at)
    const finishedAt = nowSeconds()
    const outcome = options.roundOutcome || (options.roundStatus === 'waiting' ? 'pending' : 'completed')
    const roundBody = options.roundBody
      || (startedAt > 0 ? formatCompletedRoundBody(startedAt, finishedAt, roundMetrics, outcome) : 'Completed.')
    result.push({
      ...state.transcript.liveRoundCard,
      body: roundBody,
      status: options.roundStatus || 'done',
      metadata: {
        ...(state.transcript.liveRoundCard.metadata || {}),
        metrics: roundMetrics,
        ...(startedAt > 0 ? {
          finished_at: finishedAt,
          duration_seconds: Math.max(finishedAt - startedAt, 0),
        } : {}),
        outcome,
      },
    })
  }
  if (state.transcript.liveThinkingCard) {
    result.push({
      ...state.transcript.liveThinkingCard,
      status: 'done',
    })
  }
  if (state.transcript.liveAssistantCard) {
    result.push({
      ...state.transcript.liveAssistantCard,
      body: options.finalContent || state.transcript.liveAssistantCard.body,
      status: 'done',
      metadata: {
        ...(state.transcript.liveAssistantCard.metadata || {}),
        ...(assistantFooter ? { footer_left: assistantFooter } : {}),
      },
    })
  } else if (options.finalContent?.trim()) {
    result.push(newCard('assistant', 'Model Response', options.finalContent, 'done', {
      ...(state.runtime.currentRound ? { round: state.runtime.currentRound } : {}),
      ...(assistantFooter ? { footer_left: assistantFooter } : {}),
    }))
  }
  for (const toolCard of Object.values(state.transcript.liveToolCards || {})) {
    result.push({
      ...toolCard,
      status: toolCard.status === 'running' ? 'done' : toolCard.status,
    })
  }
  return result
}

function commitLiveTranscript(
  state: AppState,
  options: {
    finalContent?: string
    roundBody?: string
    roundStatus?: string
    roundOutcome?: string
  } = {},
): AppState {
  if (!hasLiveTranscript(state)) {
    return state
  }
  const committed = [
    ...(state.transcript.committedCards || state.transcript.cards || []),
    ...liveCardsForCommit(state, options),
  ]
  return clearLiveTranscript(withCommittedCards(state, committed))
}

function clearLiveTranscript(state: AppState): AppState {
  return {
    ...state,
    runtime: {
      ...state.runtime,
      streaming: false,
      currentRound: null,
    },
    transcript: {
      ...state.transcript,
      liveRoundCard: undefined,
      liveThinkingCard: undefined,
      liveAssistantCard: undefined,
      liveToolCards: {},
      currentRoundCardId: undefined,
      currentThinkingCardId: undefined,
      currentAssistantCardId: undefined,
      toolCardIds: {},
      streamFlushAt: undefined,
    },
  }
}

function roundNumberForState(state: AppState): number {
  return Number(state.runtime.currentRound || state.transcript.liveRoundCard?.metadata?.round || 0) || 0
}

function findRoundCard(state: AppState, round: number): TranscriptCard | undefined {
  return [...getVisibleTranscriptCards(state.transcript)]
    .reverse()
    .find(card => card.kind === 'round' && Number(card.metadata?.round || 0) === round)
}

function applyAssistantFooter(state: AppState, round: number, metrics: Record<string, unknown>): AppState {
  const footer = formatMessageMetricsFooter(metrics)
  if (!footer) {
    return state
  }
  let nextState = state
  for (const card of getVisibleTranscriptCards(nextState.transcript)) {
    if (card.kind !== 'assistant' || Number(card.metadata?.round || 0) !== round) {
      continue
    }
    nextState = updateTranscriptCard(nextState, card.id, current => ({
      ...current,
      metadata: {
        ...(current.metadata || {}),
        footer_left: footer,
      },
    }))
  }
  return nextState
}

function applyRoundMetrics(
  state: AppState,
  round: number,
  incomingMetrics: Record<string, unknown>,
): AppState {
  if (round <= 0) {
    return {
      ...state,
      transcript: {
        ...state.transcript,
        lastRoundMetrics: mergeMetrics(state.transcript.lastRoundMetrics, incomingMetrics),
      },
    }
  }
  const roundCard = findRoundCard(state, round)
  const mergedMetrics = mergeMetrics(metricsFromRoundCard(roundCard), incomingMetrics)
  let nextState = roundCard
    ? updateTranscriptCard(state, roundCard.id, card => {
        const startedAt = numberValue(card.metadata?.started_at)
        const finishedAt = numberValue(card.metadata?.finished_at, startedAt)
        const outcome = String(card.metadata?.outcome || (card.status === 'running' ? 'running' : 'completed'))
        const body = outcome === 'running' && startedAt > 0
          ? formatActiveRoundBody(startedAt, mergedMetrics)
          : startedAt > 0
            ? formatCompletedRoundBody(startedAt, finishedAt || nowSeconds(), mergedMetrics, outcome)
            : card.body
        return {
          ...card,
          body,
          metadata: {
            ...(card.metadata || {}),
            metrics: mergedMetrics,
          },
        }
      })
    : state
  nextState = applyAssistantFooter(nextState, round, mergedMetrics)
  return {
    ...nextState,
    transcript: {
      ...nextState.transcript,
      lastRoundMetrics: mergedMetrics,
    },
  }
}

function activeRoundMetrics(state: AppState): Record<string, unknown> {
  return metricsFromRoundCard(findRoundCard(state, roundNumberForState(state)))
}

export function refreshActiveRoundElapsed(state: AppState, now = nowSeconds()): AppState {
  const liveRoundCard = state.transcript.liveRoundCard
  if (!liveRoundCard || liveRoundCard.kind !== 'round' || liveRoundCard.status !== 'running') {
    return state
  }
  if (String(liveRoundCard.metadata?.outcome || 'running') !== 'running') {
    return state
  }
  const startedAt = numberValue(liveRoundCard.metadata?.started_at)
  if (startedAt <= 0) {
    return state
  }
  const body = formatActiveRoundBody(startedAt, metricsFromRoundCard(liveRoundCard), now)
  if (body === liveRoundCard.body) {
    return state
  }
  return {
    ...state,
    transcript: {
      ...state.transcript,
      liveRoundCard: {
        ...liveRoundCard,
        body,
      },
    },
  }
}

export function consumeBridgeEvent(state: AppState, event: S4BridgeEvent): AppState {
  const eventType = String(event.type || '')

  if (eventType === 'round_start') {
    const round = Number(event.round || 0) || 1
    const startedAt = nowSeconds()
    const metrics: Record<string, unknown> = {}
    const card = newCard('round', `Cycle ${round}`, formatActiveRoundBody(startedAt, metrics), 'running', {
      round,
      started_at: startedAt,
      metrics,
      outcome: 'running',
    })
    const baseState = commitLiveTranscript(state)
    return {
      ...baseState,
      runtime: {
        ...baseState.runtime,
        currentRound: round,
        streaming: true,
      },
      transcript: {
        ...baseState.transcript,
        liveRoundCard: card,
        liveThinkingCard: undefined,
        liveAssistantCard: undefined,
        liveToolCards: {},
        currentRoundCardId: card.id,
        currentThinkingCardId: undefined,
        currentAssistantCardId: undefined,
        toolCardIds: {},
        lastRoundMetrics: undefined,
      },
    }
  }

  if (eventType === 'thinking_delta') {
    return appendStreamDelta(state, { thinking: String(event.delta || '') })
  }

  if (eventType === 'text_delta') {
    return appendStreamDelta(state, { assistant: String(event.delta || '') })
  }

  if (eventType === 'tool_call') {
    const toolName = String(event.tool_name || 'Tool')
    const toolId = String(event.tool_id || '').trim() || nextSyntheticToolId('tool-call')
    const body = summarizeToolArgs(event.tool_args)
    const round = roundNumberForState(state)
    const card = newCard('tool', `Tool · ${toolName}`, body || 'Running...', 'running', {
      tool_name: toolName,
      tool_id: toolId,
      tool_args: (event.tool_args as Record<string, unknown> | undefined) || {},
      round: round || undefined,
    })
    const nextState = {
      ...state,
      transcript: {
        ...state.transcript,
        liveToolCards: {
          ...state.transcript.liveToolCards,
          [toolId]: card,
        },
        toolCardIds: {
          ...state.transcript.toolCardIds,
          [toolId]: card.id,
        },
      },
    }
    const metrics = activeRoundMetrics(state)
    return applyRoundMetrics(nextState, round, {
      ...metrics,
      tool_calls: numberValue(metrics.tool_calls) + 1,
      running_tools: numberValue(metrics.running_tools) + 1,
      tools_used: Array.from(new Set([...stringList(metrics.tools_used), toolName])).sort(),
    })
  }

  if (eventType === 'tool_result') {
    const toolName = String(event.tool_name || 'Tool')
    const toolId = String(event.tool_id || '').trim()
    const body = formatToolResultBody(event)
    const status = resolveToolCardStatus(event)
    const metadata = extractToolResultMetadata(event)
    const currentToolCard = toolId ? state.transcript.liveToolCards[toolId] : undefined
    let nextState = currentToolCard
      ? {
          ...state,
          transcript: {
            ...state.transcript,
            liveToolCards: {
              ...state.transcript.liveToolCards,
              [toolId]: {
                ...currentToolCard,
                body: body || currentToolCard.body,
                status,
                metadata: {
                  ...(currentToolCard.metadata || {}),
                  tool_id: toolId,
                  tool_name: toolName,
                  ...metadata,
                },
              },
            },
          },
        }
      : toolId
        ? updateCommittedCard(state, state.transcript.toolCardIds[toolId], card => ({
            ...card,
            body: body || card.body,
            status,
            metadata: {
              ...(card.metadata || {}),
              tool_id: toolId,
              tool_name: toolName,
              ...metadata,
            },
          }))
        : {
            ...state,
            transcript: {
              ...state.transcript,
              liveToolCards: {
                ...state.transcript.liveToolCards,
                [nextSyntheticToolId('tool-result')]: newCard(
                  'tool',
                  `Tool · ${toolName}`,
                  body,
                  status,
                  {
                    tool_name: toolName,
                    ...metadata,
                  },
                ),
              },
            },
          }

    const structured = (event.structured_data as Record<string, unknown> | undefined) || {}
    const backgroundTask = structured.background_task as Record<string, unknown> | undefined
    if (backgroundTask && typeof backgroundTask.task_id === 'string') {
      const taskId = backgroundTask.task_id
      nextState = {
        ...nextState,
        tasks: {
          items: {
            ...nextState.tasks.items,
            [taskId]: {
              id: taskId,
              status: String(backgroundTask.status || 'running'),
              title: String(backgroundTask.command || backgroundTask.description || taskId),
              kind: 'background',
            },
          },
        },
      }
    }
    const round = Number(currentToolCard?.metadata?.round || state.runtime.currentRound || 0) || 0
    if (round > 0) {
      const metrics = activeRoundMetrics(nextState)
      const diffPayload = metadata.diff && typeof metadata.diff === 'object'
        ? metadata.diff as Record<string, unknown>
        : null
      const changedFile = String(diffPayload?.relative_path || diffPayload?.file_path || '').trim()
      return applyRoundMetrics(nextState, round, {
        ...metrics,
        running_tools: Math.max(numberValue(metrics.running_tools) - 1, 0),
        tool_errors: status === 'error' ? numberValue(metrics.tool_errors) + 1 : numberValue(metrics.tool_errors),
        tool_pending: status === 'pending' ? numberValue(metrics.tool_pending) + 1 : numberValue(metrics.tool_pending),
        tools_used: Array.from(new Set([...stringList(metrics.tools_used), toolName])).sort(),
        files_changed: changedFile
          ? Array.from(new Set([...stringList(metrics.files_changed), changedFile])).sort()
          : stringList(metrics.files_changed),
      })
    }
    return nextState
  }

  if (eventType === 'round_metrics') {
    const payload = Object.keys(asRecord(event.metrics)).length > 0
      ? asRecord(event.metrics)
      : Object.fromEntries(Object.entries(event).filter(([key]) => !['type', 'round'].includes(key)))
    const round = Number(event.round || state.runtime.currentRound || state.transcript.liveRoundCard?.metadata?.round || 0) || 0
    return applyRoundMetrics(state, round, payload)
  }

  if (eventType === 'runtime_snapshot') {
    const body = formatRuntimeSnapshot(event.snapshot)
    const existing = (state.transcript.committedCards || state.transcript.cards || [])
      .find(card => card.kind === 'runtime' && card.metadata?.runtime_snapshot)
    if (existing) {
      return updateCommittedCard(state, existing.id, card => ({
        ...card,
        body,
        status: state.runtime.currentRound ? 'live' : undefined,
      }))
    }
    return appendCard(state, 'runtime', 'Runtime Snapshot', body, state.runtime.currentRound ? 'live' : undefined, {
      runtime_snapshot: true,
    })
  }

  if (eventType === 'checkpoint') {
    return applyCheckpoint(state, checkpointAnnotation(asRecord(event.checkpoint)))
  }

  if (eventType === 'final') {
    const round = roundNumberForState(state)
    const roundCard = findRoundCard(state, round)
    const metrics = mergeMetrics(metricsFromRoundCard(roundCard), state.transcript.lastRoundMetrics)
    const startedAt = numberValue(roundCard?.metadata?.started_at)
    const finishedAt = nowSeconds()
    let nextState = commitLiveTranscript(state, {
      finalContent: String(event.content || ''),
      roundBody: startedAt > 0 ? formatCompletedRoundBody(startedAt, finishedAt, metrics, 'completed') : undefined,
      roundOutcome: 'completed',
    })
    nextState = maybeAppendSummaryCards(nextState)
    return nextState
  }

  if (eventType === 'system_notice') {
    return appendCard(
      state,
      'system',
      String(event.title || 'System'),
      String(event.content || ''),
      'done',
    )
  }

  if (eventType === 'interruption') {
    const pausedState = commitLiveTranscript(state, {
      roundBody: 'Paused.',
      roundStatus: 'waiting',
      roundOutcome: 'pending',
    })
    const formatted = formatInterruptionBody(event)
    return appendCard(
      {
        ...pausedState,
        permissions: {
          ...pausedState.permissions,
          pending: formatted.pending,
        },
      },
      'warning',
      formatted.title,
      formatted.body,
      'waiting',
    )
  }

  if (eventType === 'interaction_resolved') {
    return appendCard(
      {
        ...state,
        permissions: {
          ...state.permissions,
          pending: { active: false },
        },
      },
      'system',
      'Interaction Resolved',
      String(event.content || ''),
      'done',
    )
  }

  if (eventType === 'error' || eventType === 'cancelled') {
    const outcome = eventType === 'cancelled' ? 'interrupted' : 'error'
    const round = roundNumberForState(state)
    const roundCard = findRoundCard(state, round)
    const metrics = mergeMetrics(metricsFromRoundCard(roundCard), state.transcript.lastRoundMetrics)
    const startedAt = numberValue(roundCard?.metadata?.started_at)
    const flushedState = commitLiveTranscript(state, {
      roundBody: startedAt > 0 ? formatCompletedRoundBody(startedAt, nowSeconds(), metrics, outcome) : undefined,
      roundOutcome: outcome,
    })
    return appendCard(
      flushedState,
      'error',
      eventType === 'cancelled' ? 'Cancelled' : 'Error',
      String(event.error || event.content || 'Unknown error'),
      'done',
    )
  }

  return state
}

export function appendSeparator(state: AppState): AppState {
  return appendCard(state, 'separator', '', '', undefined)
}
