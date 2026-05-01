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

  const liveThinkingCard = thinking
    ? {
        ...(state.transcript.liveThinkingCard || newCard('thinking', 'Model Thinking', '', 'streaming')),
        body: `${state.transcript.liveThinkingCard?.body || ''}${thinking}`,
        status: 'streaming',
      }
    : state.transcript.liveThinkingCard
  const liveAssistantCard = assistant
    ? {
        ...(state.transcript.liveAssistantCard || newCard('assistant', 'Model Response', '', 'streaming')),
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
  } = {},
): TranscriptCard[] {
  const result: TranscriptCard[] = []
  if (state.transcript.liveRoundCard) {
    result.push({
      ...state.transcript.liveRoundCard,
      body: options.roundBody || 'Completed.',
      status: options.roundStatus || 'done',
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
    })
  } else if (options.finalContent?.trim()) {
    result.push(newCard('assistant', 'Model Response', options.finalContent, 'done'))
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

export function consumeBridgeEvent(state: AppState, event: S4BridgeEvent): AppState {
  const eventType = String(event.type || '')

  if (eventType === 'round_start') {
    const round = Number(event.round || 0) || 1
    const card = newCard('round', `Cycle ${round}`, 'Running...', 'running', { round })
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
    const card = newCard('tool', `Tool · ${toolName}`, body || 'Running...', 'running', {
      tool_name: toolName,
      tool_id: toolId,
      tool_args: (event.tool_args as Record<string, unknown> | undefined) || {},
      round: state.runtime.currentRound || undefined,
    })
    return {
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
    return nextState
  }

  if (eventType === 'round_metrics') {
    const metrics = (event.metrics as Record<string, unknown> | undefined)
      ?? (event as Record<string, unknown>)
    return {
      ...state,
      transcript: {
        ...state.transcript,
        lastRoundMetrics: metrics,
      },
    }
  }

  if (eventType === 'final') {
    let nextState = commitLiveTranscript(state, { finalContent: String(event.content || '') })
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
    })
    return appendCard(
      pausedState,
      'warning',
      'Pending Interaction',
      String(event.content || ''),
      'waiting',
    )
  }

  if (eventType === 'interaction_resolved') {
    return appendCard(
      state,
      'system',
      'Interaction Resolved',
      String(event.content || ''),
      'done',
    )
  }

  if (eventType === 'error' || eventType === 'cancelled') {
    const flushedState = commitLiveTranscript(state)
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
