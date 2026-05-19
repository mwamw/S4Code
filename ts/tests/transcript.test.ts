import { describe, expect, test } from 'bun:test'
import { getDefaultAppState } from '../src/state/AppStateStore'
import { appendStreamDelta, consumeBridgeEvent, getVisibleTranscriptCards, refreshActiveRoundElapsed } from '../src/state/transcript'

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
      ['warning', 'Pending Confirmation', 'waiting'],
    ])
  })

  test('ask user question interruption renders the question card immediately', () => {
    let state = getDefaultAppState()

    state = consumeBridgeEvent(state, { type: 'round_start', round: 1 })
    state = consumeBridgeEvent(state, {
      type: 'interruption',
      content: '需要用户回答 1 个结构化问题后才能继续执行。',
      payload: {
        message: '需要用户回答 1 个结构化问题后才能继续执行。',
        metadata: {
          interaction_type: 'ask_user_question',
          source: 'AskUserQuestion',
          questions: [
            {
              header: 'Language',
              question: 'Choose one',
              options: [
                { label: 'Python', description: 'Use Python tooling' },
                { label: 'Go', description: 'Use Go tooling' },
              ],
            },
          ],
        },
      },
    })

    const warning = state.transcript.committedCards.find(card => card.kind === 'warning')
    expect(warning?.title).toBe('Ask User Question')
    expect(warning?.status).toBe('waiting')
    expect(warning?.body).toContain('Questions:')
    expect(warning?.body).toContain('1. Language')
    expect(warning?.body).toContain('Choose one')
    expect(warning?.body).toContain('Python: Use Python tooling')
    expect(warning?.body).toContain('Use `/answer <text>` to continue.')
    expect(state.permissions.pending?.active).toBe(true)
    expect(state.permissions.pending?.title).toBe('Answer needed')
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

  test('round metrics update round body and assistant footer', () => {
    let state = getDefaultAppState()

    state = consumeBridgeEvent(state, { type: 'round_start', round: 1 })
    state = appendStreamDelta(state, { thinking: 'inspect', assistant: 'answer' })
    state = consumeBridgeEvent(state, {
      type: 'round_metrics',
      round: 1,
      metrics: {
        tool_calls: 1,
        tools_used: ['Bash'],
        files_changed: ['src/app.ts'],
        input_tokens: 210,
        output_tokens: 111,
        total_tokens: 321,
        context_used_tokens: 500,
        context_max_tokens: 1000,
        estimated_cost_usd: 0.0123,
      },
    })

    expect(state.transcript.liveThinkingCard?.metadata?.round).toBe(1)
    expect(state.transcript.liveAssistantCard?.metadata?.round).toBe(1)
    expect(state.transcript.liveRoundCard?.body).toContain('Tools 1')
    expect(state.transcript.liveRoundCard?.body).toContain('Used: Bash')
    expect(state.transcript.liveRoundCard?.body).toContain('Changed: src/app.ts')
    expect(state.transcript.liveAssistantCard?.metadata?.footer_left).toContain('Ctx 500/1,000')
    expect(state.transcript.liveAssistantCard?.metadata?.footer_left).toContain('In 210')
    expect(state.transcript.liveAssistantCard?.metadata?.footer_left).toContain('Cost $0.0123')

    state = consumeBridgeEvent(state, { type: 'final', content: 'answer' })
    const roundCard = state.transcript.committedCards.find(card => card.kind === 'round')
    const assistantCard = state.transcript.committedCards.find(card => card.kind === 'assistant')
    expect(roundCard?.body).toContain('Completed in')
    expect(roundCard?.metadata?.outcome).toBe('completed')
    expect(assistantCard?.metadata?.footer_left).toContain('Total 321')
  })

  test('active round elapsed refreshes while running', () => {
    let state = getDefaultAppState()

    state = consumeBridgeEvent(state, { type: 'round_start', round: 1 })
    const startedAt = Number(state.transcript.liveRoundCard?.metadata?.started_at)

    state = refreshActiveRoundElapsed(state, startedAt + 1.4)

    expect(state.transcript.liveRoundCard?.body).toContain('Elapsed: 1.4s')
    expect(state.transcript.liveRoundCard?.status).toBe('running')
  })

  test('runtime snapshots update one card in place', () => {
    let state = getDefaultAppState()

    state = consumeBridgeEvent(state, {
      type: 'runtime_snapshot',
      snapshot: {
        generated_at: '2026-05-19T10:00:00',
        session: { session_id: 's4-test', checkpoints: 2 },
        worktree: { active: { branch: 'main', path: '/repo' } },
        agents: [{ agent_id: 'agent-1', status: 'running', name: 'worker' }],
        tasks: [],
        background_tasks: [],
        context: { used_tokens: 10, max_tokens: 100, remaining_tokens: 90, usage_percent: '10%' },
      },
    })
    state = consumeBridgeEvent(state, {
      type: 'runtime_snapshot',
      snapshot: {
        generated_at: '2026-05-19T10:00:01',
        session: { session_id: 's4-test', checkpoints: 3 },
      },
    })

    const runtimeCards = state.transcript.committedCards.filter(card => card.kind === 'runtime')
    expect(runtimeCards).toHaveLength(1)
    expect(runtimeCards[0].body).toContain('2026-05-19T10:00:01')
    expect(runtimeCards[0].body).toContain('checkpoints=3')
  })

  test('checkpoint events annotate the latest eligible card', () => {
    let state = getDefaultAppState()

    state = consumeBridgeEvent(state, { type: 'round_start', round: 1 })
    state = appendStreamDelta(state, { assistant: 'done' })
    state = consumeBridgeEvent(state, { type: 'final', content: 'done' })
    state = consumeBridgeEvent(state, {
      type: 'checkpoint',
      checkpoint: {
        checkpoint_id: 'cp-1',
        label: 'after response',
        reason: 'after_prompt',
        history_messages: 5,
      },
    })

    const assistantCard = state.transcript.committedCards.find(card => card.kind === 'assistant')
    expect(assistantCard?.metadata?.checkpoints).toEqual([
      {
        checkpoint_id: 'cp-1',
        label: 'after response',
        reason: 'after_prompt',
        history_messages: 5,
        created_at: '',
      },
    ])
  })
})
