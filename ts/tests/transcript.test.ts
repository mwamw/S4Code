import { describe, expect, test } from 'bun:test'
import { getDefaultAppState } from '../src/state/AppStateStore'
import { appendStreamDelta, consumeBridgeEvent, getVisibleTranscriptCards } from '../src/state/transcript'

describe('transcript state', () => {
  test('live assistant text commits once on final', () => {
    let state = getDefaultAppState()

    state = consumeBridgeEvent(state, { type: 'round_start', round: 1 })
    state = appendStreamDelta(state, { assistant: 'hel' })
    state = appendStreamDelta(state, { assistant: 'lo' })
    expect(getVisibleTranscriptCards(state.transcript).some(card => card.id === state.transcript.liveAssistantCard?.id)).toBe(true)

    state = consumeBridgeEvent(state, {
      type: 'round_metrics',
      metrics: {
        tools_used: [],
        files_changed: [],
      },
    })
    state = consumeBridgeEvent(state, { type: 'final', content: 'hello' })

    const assistantCards = state.transcript.committedCards.filter(card => card.kind === 'assistant')
    expect(assistantCards).toHaveLength(1)
    expect(assistantCards[0].body).toBe('hello')
    expect(state.transcript.liveAssistantCard).toBeUndefined()
  })

  test('error flushes live cards before adding error card', () => {
    let state = getDefaultAppState()

    state = consumeBridgeEvent(state, { type: 'round_start', round: 2 })
    state = appendStreamDelta(state, { assistant: 'partial' })
    state = consumeBridgeEvent(state, { type: 'error', error: 'failed' })

    expect(state.transcript.committedCards.map(card => card.kind)).toEqual([
      'round',
      'assistant',
      'error',
    ])
    expect(state.transcript.liveToolCards).toEqual({})
  })

  test('interruption commits live tool cards before the warning card', () => {
    let state = getDefaultAppState()

    state = consumeBridgeEvent(state, { type: 'round_start', round: 1 })
    state = consumeBridgeEvent(state, {
      type: 'tool_call',
      tool_name: 'Bash',
      tool_id: 'tool-1',
      tool_args: { command: 'echo hi' },
    })
    state = consumeBridgeEvent(state, {
      type: 'interruption',
      content: 'Approval required',
    })

    expect(state.transcript.liveToolCards).toEqual({})
    expect(state.transcript.committedCards.map(card => [card.kind, card.title, card.status])).toEqual([
      ['round', 'Cycle 1', 'waiting'],
      ['tool', 'Tool · Bash', 'done'],
      ['warning', 'Pending Interaction', 'waiting'],
    ])
  })

  test('new rounds commit previous live transcript instead of dropping it', () => {
    let state = getDefaultAppState()

    state = consumeBridgeEvent(state, { type: 'round_start', round: 1 })
    state = consumeBridgeEvent(state, {
      type: 'tool_call',
      tool_name: 'Bash',
      tool_id: 'tool-1',
      tool_args: { command: 'echo hi' },
    })
    state = consumeBridgeEvent(state, { type: 'round_start', round: 2 })

    expect(state.transcript.committedCards.map(card => [card.kind, card.title, card.status])).toEqual([
      ['round', 'Cycle 1', 'done'],
      ['tool', 'Tool · Bash', 'done'],
    ])
    expect(state.transcript.liveRoundCard?.title).toBe('Cycle 2')
    expect(state.transcript.liveToolCards).toEqual({})
  })

  test('tool call and result are summarized instead of fully expanded', () => {
    let state = getDefaultAppState()

    state = consumeBridgeEvent(state, { type: 'round_start', round: 1 })
    state = consumeBridgeEvent(state, {
      type: 'tool_call',
      tool_name: 'ReadFile',
      tool_id: 'tool-2',
      tool_args: {
        file_path: '/tmp/example.txt',
        cwd: '/tmp',
        extra: 'hidden',
        another: 'hidden-too',
        more: 'hidden-three',
      },
    })
    state = consumeBridgeEvent(state, {
      type: 'tool_result',
      tool_name: 'ReadFile',
      tool_id: 'tool-2',
      content: 'first line\nsecond line\nthird line',
    })

    const toolCard = state.transcript.liveToolCards['tool-2']
    expect(toolCard?.body).toBe('first line\n... 2 more line(s) hidden')
    expect(toolCard?.status).toBe('done')
    expect(toolCard?.metadata?.tool_name).toBe('ReadFile')
  })

  test('background task tool results use the python-style summary', () => {
    let state = getDefaultAppState()

    state = consumeBridgeEvent(state, { type: 'round_start', round: 1 })
    state = consumeBridgeEvent(state, {
      type: 'tool_call',
      tool_name: 'Bash',
      tool_id: 'tool-3',
      tool_args: { command: 'npm test' },
    })
    state = consumeBridgeEvent(state, {
      type: 'tool_result',
      tool_name: 'Bash',
      tool_id: 'tool-3',
      content: 'background started',
      structured_data: {
        background_task: {
          task_id: 'task-1',
          status: 'running',
          command: 'npm test --watch',
        },
      },
    })

    const toolCard = state.transcript.liveToolCards['tool-3']
    expect(toolCard?.body).toContain('Started background task `task-1`.')
    expect(toolCard?.body).toContain('Use `/task output task-1` to stream logs.')
  })

  test('missing tool ids do not overwrite tool cards', () => {
    let state = getDefaultAppState()

    state = consumeBridgeEvent(state, { type: 'round_start', round: 1 })
    state = consumeBridgeEvent(state, {
      type: 'tool_call',
      tool_name: 'ReadFile',
      tool_args: { file_path: '/tmp/a.txt' },
    })
    state = consumeBridgeEvent(state, {
      type: 'tool_call',
      tool_name: 'Edit',
      tool_args: { file_path: '/tmp/b.txt' },
    })

    const callCards = Object.values(state.transcript.liveToolCards)
    expect(callCards).toHaveLength(2)
    expect(new Set(callCards.map(card => card.title)).size).toBe(2)

    state = consumeBridgeEvent(state, {
      type: 'tool_result',
      tool_name: 'Search',
      content: 'first line\nsecond line',
    })

    const resultCards = Object.values(state.transcript.liveToolCards)
    expect(resultCards).toHaveLength(3)
    expect(resultCards.some(card => card.title === 'Tool · Search')).toBe(true)
  })
})
