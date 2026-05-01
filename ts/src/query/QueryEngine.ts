import type { AppState } from '../state/AppStateStore'
import { appendCard, appendSeparator, appendStreamDelta, consumeBridgeEvent } from '../state/transcript'
import { getCommands, matchCommands, parseCommand, runCommand } from '../commands'
import type { BridgeClient } from '../runtime/bridgeClient'
import type { Command } from '../types/command'
import type { S4BridgeEvent } from '../types/bridge'

function stableJson(value: unknown): string {
  return JSON.stringify(value) || 'null'
}

function sidebarSnapshot(state: AppState): string {
  return stableJson({
    sidebar: state.sidebar,
    context: state.context,
    permissions: state.permissions,
    skills: state.skills,
    mcp: state.mcp,
  })
}

export type QueryEngineConfig = {
  bridge: BridgeClient
  getAppState: () => AppState
  setAppState: (updater: (prev: AppState) => AppState) => void
}

export class QueryEngine {
  readonly bridge: BridgeClient
  readonly commands: Command[]
  private getAppState: () => AppState
  private setAppState: (updater: (prev: AppState) => AppState) => void
  private pendingThinkingText = ''
  private pendingAssistantText = ''
  private streamFlushTimer: ReturnType<typeof setTimeout> | null = null
  private readonly streamFlushMs = 75

  constructor(config: QueryEngineConfig) {
    this.bridge = config.bridge
    this.commands = getCommands()
    this.getAppState = config.getAppState
    this.setAppState = config.setAppState
  }

  private recordCommandUsage(name: string): void {
    this.setAppState(prev => ({
      ...prev,
      palette: {
        ...prev.palette,
        recentCommands: [name, ...prev.palette.recentCommands.filter(item => item !== name)].slice(0, 12),
      },
    }))
  }

  private clearStreamTimer(): void {
    if (this.streamFlushTimer) {
      clearTimeout(this.streamFlushTimer)
      this.streamFlushTimer = null
    }
  }

  flushStreamBuffer(): void {
    if (!this.pendingThinkingText && !this.pendingAssistantText) {
      this.clearStreamTimer()
      return
    }
    const thinking = this.pendingThinkingText
    const assistant = this.pendingAssistantText
    this.pendingThinkingText = ''
    this.pendingAssistantText = ''
    this.clearStreamTimer()
    this.setAppState(prev => appendStreamDelta(prev, { thinking, assistant }))
  }

  private scheduleStreamFlush(): void {
    if (this.streamFlushTimer) {
      return
    }
    this.streamFlushTimer = setTimeout(() => {
      this.flushStreamBuffer()
    }, this.streamFlushMs)
  }

  private consumeRuntimeEvent(event: S4BridgeEvent): void {
    const eventType = String(event.type || '')
    if (eventType === 'thinking_delta') {
      this.pendingThinkingText += String(event.delta || '')
      this.scheduleStreamFlush()
      return
    }
    if (eventType === 'text_delta') {
      this.pendingAssistantText += String(event.delta || '')
      this.scheduleStreamFlush()
      return
    }
    this.flushStreamBuffer()
    this.setAppState(prev => consumeBridgeEvent(prev, event))
  }

  async handleInput(text: string): Promise<void> {
    const raw = text.trim()
    if (!raw) {
      return
    }
    try {
      const invocation = parseCommand(this.commands, raw)
      if (invocation) {
        this.recordCommandUsage(invocation.command.name)
        await runCommand(invocation, this)
        return
      }
      await this.submitPrompt(raw)
    } catch (error) {
      this.flushStreamBuffer()
      const message = error instanceof Error ? error.message : String(error)
      this.setAppState(prev => ({
        ...appendCard(prev, 'error', 'Error', message, 'done'),
        runtime: {
          ...prev.runtime,
          busy: false,
          streaming: false,
        },
      }))
    }
  }

  async showHelp(): Promise<void> {
    const lines = [
      'S4Code quick start',
      '',
      'Core commands:',
      ...this.commands.map(command => `- /${command.name}${command.argumentHint ? ` ${command.argumentHint}` : ''}: ${command.description}`),
    ]
    this.setAppState(prev => appendCard(prev, 'system', 'Help', lines.join('\n'), 'done'))
  }

  async showView(view: string, args: string): Promise<void> {
    const params: Record<string, unknown> = {}
    if (view === 'task_detail') {
      params.task_id = args.trim()
    }
    if (view === 'task_output') {
      params.task_id = args.trim()
    }
    if (view === 'diff' && args.trim()) {
      params.target = args.trim()
    }
    const result = await this.bridge.renderView(view, params)
    this.setAppState(prev => appendCard(prev, 'system', result.title, result.text, 'done'))
    await this.refreshSidebar(true)
  }

  async showTaskDetail(taskId: string): Promise<void> {
    await this.showView('task_detail', taskId)
  }

  async showTaskOutput(taskId: string): Promise<void> {
    await this.showView('task_output', taskId)
  }

  async showDiff(target: string): Promise<void> {
    await this.showView('diff', target)
  }

  async loadSession(sessionId: string): Promise<void> {
    const result = await this.bridge.runAction('load_session', { session_id: sessionId.trim() })
    const init = result.init
    if (init !== undefined) {
      this.setAppState(() => this.buildStateFromInit(init))
    } else {
      this.setAppState(prev => appendCard(prev, 'system', 'Session', result.text, 'done'))
    }
  }

  async setModel(target: string): Promise<void> {
    const result = await this.bridge.runAction('set_model', { target: target.trim() })
    this.setAppState(prev => appendCard(prev, 'system', 'Model', result.text, 'done'))
    await this.refreshSidebar(true)
  }

  async setPermissionMode(mode: string): Promise<void> {
    const result = await this.bridge.runAction('set_permission_mode', { mode: mode.trim() })
    this.setAppState(prev => appendCard(prev, 'system', 'Permissions', result.text, 'done'))
    await this.refreshSidebar(true)
  }

  async compactHistory(rawArg: string): Promise<void> {
    const maxTokens = rawArg.trim() ? Number(rawArg.trim()) : undefined
    const result = await this.bridge.runAction('compact_history', {
      max_tokens: Number.isFinite(maxTokens) ? maxTokens : undefined,
    })
    this.setAppState(prev => appendCard(prev, 'system', 'Context Compaction', result.text, 'done'))
    await this.refreshSidebar(true)
  }

  async stopTask(taskId: string): Promise<void> {
    const result = await this.bridge.runAction('stop_task', { task_id: taskId.trim() })
    this.setAppState(prev => appendCard(prev, 'system', 'Task Stop', result.text, 'done'))
    await this.refreshSidebar(true)
  }

  async resolvePending(action: 'approve' | 'deny' | 'answer', answer: string): Promise<void> {
    this.setAppState(prev => ({
      ...prev,
      runtime: {
        ...prev.runtime,
        busy: true,
        streaming: false,
      },
    }))
    try {
      await this.bridge.resolvePending(action, answer, event => {
        this.consumeRuntimeEvent(event)
      })
      this.flushStreamBuffer()
      this.setAppState(prev => appendSeparator({
        ...prev,
        runtime: {
          ...prev.runtime,
          busy: false,
        },
      }))
      await this.refreshSidebar(true)
    } catch (error) {
      this.flushStreamBuffer()
      const message = error instanceof Error ? error.message : String(error)
      this.setAppState(prev => ({
        ...appendCard(prev, 'error', 'Error', message, 'done'),
        runtime: {
          ...prev.runtime,
          busy: false,
          streaming: false,
        },
      }))
    }
  }

  async submitPrompt(prompt: string): Promise<void> {
    this.setAppState(prev => ({
      ...appendCard(prev, 'user', 'You', prompt, 'done'),
      runtime: {
        ...prev.runtime,
        busy: true,
        streaming: false,
      },
    }))
    try {
      await this.bridge.submitPrompt(prompt, event => {
        this.consumeRuntimeEvent(event)
      })
      this.flushStreamBuffer()
      this.setAppState(prev => appendSeparator({
        ...prev,
        runtime: {
          ...prev.runtime,
          busy: false,
        },
      }))
      await this.refreshSidebar(true)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      this.setAppState(prev => ({
        ...appendCard(prev, 'error', 'Error', message, 'done'),
        runtime: {
          ...prev.runtime,
          busy: false,
        },
      }))
    }
  }

  async refreshSidebar(force = false): Promise<void> {
    const sidebar = await this.bridge.getSidebar(force)
    this.setAppState(prev => {
      const next: AppState = {
        ...prev,
        sidebar,
        context: sidebar.context || prev.context,
        permissions: {
          ...prev.permissions,
          mode: String(sidebar.permission_mode || prev.permissions.mode),
          rules: Number(sidebar.permission_rules || prev.permissions.rules),
          pending: (sidebar.pending as typeof prev.permissions.pending) || prev.permissions.pending,
        },
        skills: {
          active: [...(sidebar.skills?.active || [])],
          queued: [...(sidebar.skills?.queued || [])],
        },
        mcp: {
          enabled: Boolean(sidebar.mcp?.enabled),
          configured: Number(sidebar.mcp?.configured || 0),
          connected: Number(sidebar.mcp?.connected || 0),
          disabled: Number(sidebar.mcp?.disabled || 0),
          unavailable: Number(sidebar.mcp?.unavailable || 0),
        },
      }
      return sidebarSnapshot(prev) === sidebarSnapshot(next) ? prev : next
    })
  }

  async pollRuntime(): Promise<void> {
    const result = await this.bridge.pollRuntimeNotices()
    this.setAppState(prev => {
      const currentSidebar = result.sidebar || prev.sidebar
      if ((result.notices || []).length === 0) {
        const nextSnapshot = stableJson({
          sidebar: currentSidebar,
          context: currentSidebar?.context || prev.context,
        })
        const prevSnapshot = stableJson({
          sidebar: prev.sidebar,
          context: prev.context,
        })
        if (nextSnapshot === prevSnapshot) {
          return prev
        }
      }
      let next = prev
      for (const notice of result.notices || []) {
        next = consumeBridgeEvent(next, notice)
      }
      const updated: AppState = {
        ...next,
        sidebar: currentSidebar,
        context: currentSidebar?.context || next.context,
      }
      return stableJson({
        transcript: updated.transcript,
        sidebar: updated.sidebar,
        context: updated.context,
      }) === stableJson({
        transcript: prev.transcript,
        sidebar: prev.sidebar,
        context: prev.context,
      })
        ? prev
        : updated
    })
  }

  getPaletteCommands(input: string): Command[] {
    const raw = input.trim()
    if (!raw.startsWith('/')) {
      return []
    }
    const state = this.getAppState()
    return matchCommands(this.commands, raw, state.palette.recentCommands, state)
  }

  buildStateFromInit(init: {
    cwd: string
    session_id: string
    project_name: string
    project_root: string
    branch: string
    model: string
    provider: string
    permission_mode: string
    sidebar: AppState['sidebar']
    context: AppState['context']
    pending: AppState['permissions']['pending']
    welcome: { kind?: string; title?: string; body?: string }
    startup_notices: Array<{ kind?: string; title?: string; body?: string }>
  }): AppState {
    let state: AppState = {
      ...this.getAppState(),
      session: {
        id: init.session_id,
        title: `${init.project_name} session`,
        restored: false,
        dirty: false,
        checkpointCount: 0,
      },
      project: {
        cwd: init.cwd,
        root: init.project_root,
        projectName: init.project_name,
        branch: init.branch,
      },
      model: {
        model: init.model,
        provider: init.provider,
        profile: 'default',
      },
      permissions: {
        mode: init.permission_mode,
        rules: Number(init.sidebar.permission_rules || 0),
        pending: init.pending,
      },
      context: init.context,
      sidebar: init.sidebar,
      transcript: {
        committedCards: [],
        liveToolCards: {},
        cards: [],
        toolCardIds: {},
      },
      runtime: {
        busy: false,
        streaming: false,
        renderMode: 'interactive',
        autoFollowTranscript: true,
        currentRound: null,
        recentNotices: [],
      },
      skills: {
        active: [...(init.sidebar.skills?.active || [])],
        queued: [...(init.sidebar.skills?.queued || [])],
      },
      mcp: {
        enabled: Boolean(init.sidebar.mcp?.enabled),
        configured: Number(init.sidebar.mcp?.configured || 0),
        connected: Number(init.sidebar.mcp?.connected || 0),
        disabled: Number(init.sidebar.mcp?.disabled || 0),
        unavailable: Number(init.sidebar.mcp?.unavailable || 0),
      },
    }
    state = appendCard(state, 'system', init.welcome.title || 'Welcome', init.welcome.body || '', 'done')
    for (const notice of init.startup_notices) {
      state = appendCard(state, 'system', notice.title || 'Notice', notice.body || '', 'done')
    }
    return state
  }

  async close(): Promise<void> {
    try {
      this.flushStreamBuffer()
      await this.bridge.close()
    } finally {
      this.clearStreamTimer()
      this.bridge.terminate()
    }
  }
}
