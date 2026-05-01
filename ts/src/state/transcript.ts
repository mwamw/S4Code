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

function summarizeToolArgs(toolArgs: unknown): string {
  if (!toolArgs || typeof toolArgs !== 'object') {
    return ''
  }
  const record = toolArgs as Record<string, unknown>
  if (typeof record.command === 'string' && record.command.trim()) {
    return record.command.trim()
  }
  return JSON.stringify(record, null, 2)
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

function liveCardsForCommit(state: AppState, finalContent?: string): TranscriptCard[] {
  const result: TranscriptCard[] = []
  if (state.transcript.liveRoundCard) {
    result.push({
      ...state.transcript.liveRoundCard,
      body: 'Completed.',
      status: 'done',
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
      body: finalContent || state.transcript.liveAssistantCard.body,
      status: 'done',
    })
  } else if (finalContent?.trim()) {
    result.push(newCard('assistant', 'Model Response', finalContent, 'done'))
  }
  for (const toolCard of Object.values(state.transcript.liveToolCards || {})) {
    result.push({
      ...toolCard,
      status: toolCard.status === 'running' ? 'done' : toolCard.status,
    })
  }
  return result
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
    return {
      ...state,
      runtime: {
        ...state.runtime,
        currentRound: round,
        streaming: true,
      },
      transcript: {
        ...state.transcript,
        liveRoundCard: card,
        liveThinkingCard: undefined,
        liveAssistantCard: undefined,
        liveToolCards: {},
        currentRoundCardId: card.id,
        currentThinkingCardId: undefined,
        currentAssistantCardId: undefined,
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
    const toolId = String(event.tool_id || '')
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
    const toolId = String(event.tool_id || '')
    const content = String(event.content || '')
    const currentToolCard = state.transcript.liveToolCards[toolId]
    let nextState = currentToolCard
      ? {
          ...state,
          transcript: {
            ...state.transcript,
            liveToolCards: {
              ...state.transcript.liveToolCards,
              [toolId]: {
                ...currentToolCard,
                body: content || currentToolCard.body,
                status: 'done',
              },
            },
          },
        }
      : updateCommittedCard(state, state.transcript.toolCardIds[toolId], card => ({
          ...card,
          body: content || card.body,
          status: 'done',
        }))

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
    const committed = [
      ...(state.transcript.committedCards || state.transcript.cards || []),
      ...liveCardsForCommit(state, String(event.content || '')),
    ]
    let nextState = clearLiveTranscript(withCommittedCards(state, committed))
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
    return appendCard(
      state,
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
    return appendCard(
      clearLiveTranscript(state),
      'error',
      'Error',
      String(event.error || event.content || 'Unknown error'),
      'done',
    )
  }

  return state
}

export function appendSeparator(state: AppState): AppState {
  return appendCard(state, 'separator', '', '', undefined)
}
