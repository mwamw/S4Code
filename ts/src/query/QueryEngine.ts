import type { AppState, TranscriptCardKind } from '../state/AppStateStore'
import { appendCard, appendSeparator, appendStreamDelta, consumeBridgeEvent } from '../state/transcript'
import { getCommands, matchCommands } from '../commands'
import type { BridgeClient } from '../runtime/bridgeClient'
import { isBridgeClosedError } from '../runtime/bridgeClient'
import type { Command } from '../types/command'
import type { CommandPaletteEntryPayload, S4BridgeEvent } from '../types/bridge'
import type { PaletteEntry } from '../state/AppStateStore'

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

function isQuitInput(value: string): boolean {
  return ['/exit', '/quit', '/q'].includes(value.trim().toLowerCase())
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
  private paletteTimer: ReturnType<typeof setTimeout> | null = null
  private paletteRequestSeq = 0
  private readonly paletteDebounceMs = 220
  private paletteCache = new Map<string, { stateKey: string; entries: PaletteEntry[] }>()
  private quitListeners = new Set<() => void>()
  private closing = false

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

  onQuit(listener: () => void): () => void {
    this.quitListeners.add(listener)
    return () => this.quitListeners.delete(listener)
  }

  async quit(): Promise<'quit'> {
    this.closing = true
    await this.close()
    for (const listener of this.quitListeners) {
      listener()
    }
    return 'quit'
  }

  async handleInput(text: string): Promise<void | 'quit'> {
    const raw = text.trim()
    if (!raw) {
      return
    }
    if (isQuitInput(raw)) {
      return this.quit()
    }
    try {
      if (raw.startsWith('/')) {
        return this.executeSlashCommand(raw)
      }
      await this.submitPrompt(raw)
    } catch (error) {
      this.flushStreamBuffer()
      const message = error instanceof Error ? error.message : String(error)
      this.setAppState(prev => ({
        ...consumeBridgeEvent(prev, { type: 'error', error: message }),
        runtime: {
          ...prev.runtime,
          busy: false,
          streaming: false,
        },
      }))
    }
  }

  private normalizePaletteEntry(entry: CommandPaletteEntryPayload): PaletteEntry {
    return {
      label: String(entry.label || ''),
      description: String(entry.description || ''),
      insertText: String(entry.insert_text || ''),
      executeText: String(entry.execute_text || ''),
      mode: entry.mode === 'execute' ? 'execute' : 'insert',
      aliases: Array.isArray(entry.aliases) ? entry.aliases.map(item => String(item)) : [],
    }
  }

  private localPaletteFallback(input: string): { stateKey: string; entries: PaletteEntry[] } {
    const state = this.getAppState()
    const commands = matchCommands(this.commands, input, state.palette.recentCommands, state)
    return {
      stateKey: `local:${input}`,
      entries: commands.map(command => ({
        label: `/${command.name}${command.argumentHint ? ` ${command.argumentHint}` : ''}`,
        description: command.description,
        insertText: `/${command.name}${command.argumentHint ? ' ' : ''}`,
        executeText: `/${command.name}`,
        mode: command.argumentHint ? 'insert' : 'execute',
        aliases: command.aliases || [],
      })),
    }
  }

  private shouldUseBackendPalette(input: string): boolean {
    return String(input || '').trim().startsWith('/')
  }

  private backendPaletteDelay(input: string): number {
    return String(input || '').trim() === '/' ? 0 : this.paletteDebounceMs
  }

  refreshPalette(input: string): void {
    const text = String(input || '')
    this.paletteRequestSeq += 1
    const requestSeq = this.paletteRequestSeq
    if (this.paletteTimer) {
      clearTimeout(this.paletteTimer)
      this.paletteTimer = null
    }
    if (!text.trim().startsWith('/')) {
      this.setAppState(prev => ({
        ...prev,
        palette: {
          ...prev.palette,
          entries: [],
          selection: 0,
          stateKey: '',
          loading: false,
          sourceText: text,
        },
      }))
      return
    }

    const fallback = this.localPaletteFallback(text)
    const useBackend = this.shouldUseBackendPalette(text)
    const cached = this.paletteCache.get(text)
    if (cached) {
      this.setAppState(prev => ({
        ...prev,
        palette: {
          ...prev.palette,
          entries: cached.entries,
          selection: cached.stateKey === prev.palette.stateKey ? prev.palette.selection : 0,
          stateKey: cached.stateKey,
          loading: false,
          sourceText: text,
        },
      }))
    } else {
      this.setAppState(prev => ({
        ...prev,
        palette: {
          ...prev.palette,
          entries: fallback.entries,
          selection: fallback.stateKey === prev.palette.stateKey ? Math.min(prev.palette.selection, Math.max(fallback.entries.length - 1, 0)) : 0,
          stateKey: fallback.stateKey,
          loading: useBackend,
          sourceText: text,
        },
      }))
    }

    if (!useBackend) {
      return
    }
    this.paletteTimer = setTimeout(() => {
      void this.loadPaletteNow(text, requestSeq)
    }, this.backendPaletteDelay(text))
  }

  async loadPaletteNow(input: string, requestSeq = ++this.paletteRequestSeq): Promise<void> {
    const text = String(input || '')
    if (!text.trim().startsWith('/')) {
      return
    }
    try {
      const payload = await this.bridge.commandPalette(text)
      if (requestSeq !== this.paletteRequestSeq || this.getAppState().ui.input !== text) {
        return
      }
      const entries = (payload.entries || []).map(entry => this.normalizePaletteEntry(entry))
      const stateKey = String(payload.state_key || '')
      this.paletteCache.set(text, { stateKey, entries })
      this.setAppState(prev => ({
        ...prev,
        palette: {
          ...prev.palette,
          entries,
          selection: stateKey === prev.palette.stateKey ? Math.min(prev.palette.selection, Math.max(entries.length - 1, 0)) : 0,
          stateKey,
          loading: false,
          sourceText: text,
        },
      }))
    } catch {
      if (requestSeq !== this.paletteRequestSeq || this.getAppState().ui.input !== text) {
        return
      }
      const fallback = this.localPaletteFallback(text)
      this.setAppState(prev => ({
        ...prev,
        palette: {
          ...prev.palette,
          entries: fallback.entries,
          selection: 0,
          stateKey: fallback.stateKey,
          loading: false,
          sourceText: text,
        },
      }))
    }
  }

  async executeSlashCommand(text: string): Promise<void | 'quit'> {
    const raw = text.trim()
    const result = await this.bridge.executeCommand(raw)
    if (!result.handled) {
      await this.submitPrompt(raw)
      return
    }

    const commandName = String(result.command_name || raw.slice(1).split(/\s+/, 1)[0])
    this.recordCommandUsage(commandName)

    const metadata = result.metadata || {}
    this.applyLocalCommandSideEffects(raw, metadata)
    const engineAction = String(metadata.engine_action || '')
    if (engineAction === 'confirm_pending') {
      await this.resolvePending('approve', String(metadata.answer || ''))
      return
    }
    if (engineAction === 'deny_pending') {
      await this.resolvePending('deny', String(metadata.answer || ''))
      return
    }
    if (engineAction === 'answer_pending') {
      await this.resolvePending('answer', String(metadata.answer || ''))
      return
    }

    if (result.init) {
      this.setAppState(() => {
        const hydrated = this.buildStateFromInit(result.init!)
        return result.message
          ? appendCard(hydrated, 'system', 'System', String(result.message), 'done')
          : hydrated
      })
    } else {
      const sidebar = result.sidebar
      if (result.message || sidebar) {
        this.setAppState(prev => {
          const withMessage = result.message
            ? appendCard(prev, 'system', 'System', String(result.message), 'done')
            : prev
          return sidebar ? this.applySidebarPayload(withMessage, sidebar) : withMessage
        })
      } else {
        await this.refreshSidebar(true)
      }
    }

    if (result.should_query && result.query) {
      await this.submitPrompt(result.query)
    }

    if (result.exit_requested) {
      return this.quit()
    }
  }

  private applyLocalCommandSideEffects(raw: string, metadata: Record<string, unknown>): void {
    const commandName = raw.slice(1).split(/\s+/, 1)[0]?.toLowerCase() || ''
    if (commandName === 'sidebar') {
      const arg = raw.slice('/sidebar'.length).trim().toLowerCase()
      this.setAppState(prev => ({
        ...prev,
        ui: {
          ...prev.ui,
          sidebarVisible: arg
            ? ['show', 'on', 'open'].includes(arg)
            : !prev.ui.sidebarVisible,
        },
      }))
    }
    if (commandName === 'theme') {
      const target = raw.slice('/theme'.length).trim()
      if (target && !['list', 'ls', 'show'].includes(target.toLowerCase())) {
        this.setAppState(prev => ({
          ...prev,
          ui: {
            ...prev.ui,
            theme: target,
          },
        }))
      }
    }
    if (String(metadata.ui_action || '') === 'copy_to_clipboard') {
      this.copyTranscriptToTerminalClipboard(String(metadata.copy_target || 'transcript'))
    }
  }

  private copyTranscriptToTerminalClipboard(target: string): void {
    const state = this.getAppState()
    const committed = state.transcript.committedCards || state.transcript.cards || []
    const cards = target === 'last'
      ? committed.slice(-1)
      : committed
    const text = cards
      .filter(card => card.kind !== 'separator')
      .map(card => `${card.title}\n${card.body}`.trim())
      .filter(Boolean)
      .join('\n\n')
    if (!text) {
      this.setAppState(prev => appendCard(prev, 'system', 'Copy', 'Nothing to copy.', 'done'))
      return
    }
    try {
      process.stdout.write(`\u001b]52;c;${Buffer.from(text, 'utf8').toString('base64')}\u0007`)
      this.setAppState(prev => appendCard(prev, 'system', 'Copy', `Copied ${target === 'last' ? 'latest card' : 'transcript'} to the terminal clipboard.`, 'done'))
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      this.setAppState(prev => appendCard(prev, 'error', 'Copy Failed', message, 'done'))
    }
  }

  async showHelp(): Promise<void> {
    const grouped = new Map<string, Command[]>()
    for (const command of this.commands) {
      const category = command.category || 'core'
      grouped.set(category, [...(grouped.get(category) || []), command])
    }
    const lines = [
      'S4Code help',
      '',
      'Common workflows:',
      '- Inspect state: /status, /context, /tasks, /pending',
      '- Continue a saved session: /session list, then /session load <id>',
      '- Resolve a pause: /confirm, /deny, or /answer <text>',
      '- Review work: /diff, then /review [target]',
      '- Manage runtime: /model <profile>, /permissions ..., /compact',
      '',
      'Commands:',
    ]
    for (const category of ['core', 'workspace', 'session', 'runtime', 'approval', 'debug']) {
      const commands = [...(grouped.get(category) || [])].sort((left, right) => left.name.localeCompare(right.name))
      if (!commands.length) {
        continue
      }
      lines.push('', `${category}:`)
      for (const command of commands) {
        lines.push(`- /${command.name}${command.argumentHint ? ` ${command.argumentHint}` : ''}: ${command.description}`)
      }
    }
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
    if (view === 'agent_detail') {
      params.agent_id = args.trim()
    }
    if (view === 'mcp_server' || view === 'mcp_tools' || view === 'mcp_resources') {
      params.server_name = args.trim()
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

  async runActionCard(title: string, action: string, params: Record<string, unknown> = {}): Promise<void> {
    const result = await this.bridge.runAction(action, params)
    this.setAppState(prev => appendCard(prev, 'system', title, result.text, 'done'))
    await this.refreshSidebar(true)
  }

  async renameSession(title: string): Promise<void> {
    await this.runActionCard('Session', 'rename_session', { title: title.trim() })
  }

  async forkSession(title: string): Promise<void> {
    await this.runActionCard('Session', 'fork_session', { title: title.trim() || undefined })
  }

  async rewindSession(target: string): Promise<void> {
    await this.runActionCard('Session Rewind', 'rewind_session', { target: target.trim() || undefined })
  }

  async queueSkill(name: string): Promise<void> {
    await this.runActionCard('Skills', 'queue_skill', { name: name.trim() })
  }

  async clearTurnSkills(): Promise<void> {
    await this.runActionCard('Skills', 'clear_turn_skills')
  }

  async enterWorktree(name: string): Promise<void> {
    await this.runActionCard('Worktree', 'enter_worktree', { name: name.trim() || undefined })
  }

  async exitWorktree(args: string): Promise<void> {
    const tokens = args.trim().split(/\s+/).filter(Boolean)
    const action = tokens.find(token => token !== 'discard') || 'keep'
    const discardChanges = tokens.includes('discard')
    await this.runActionCard('Worktree', 'exit_worktree', { action, discard_changes: discardChanges })
  }

  async updatePermission(args: string): Promise<void> {
    const tokens = args.trim().split(/\s+/).filter(Boolean)
    const [first, second, ...rest] = tokens
    if (!first || first === 'show') {
      await this.showView('permissions', '')
      return
    }
    if (first === 'history') {
      await this.showView('permission_history', '')
      return
    }
    if (first === 'mode') {
      await this.setPermissionMode(second || '')
      return
    }
    if (first === 'clear') {
      await this.runActionCard('Permissions', 'clear_permissions', { source: second || 'session' })
      return
    }
    if (['allow', 'deny', 'ask'].includes(first)) {
      await this.runActionCard('Permissions', 'permission_rule', {
        behavior: first,
        tool_name: second || '',
        tokens: rest,
      })
      return
    }
    await this.setPermissionMode(args)
  }

  async runMcpAction(action: 'connect_mcp' | 'disconnect_mcp' | 'refresh_mcp', serverName: string): Promise<void> {
    await this.runActionCard('MCP', action, { server_name: serverName.trim() || undefined })
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

  async interrupt(reason = 'User pressed Esc in the S4Code TS TUI.'): Promise<void> {
    try {
      const result = await this.bridge.interrupt(reason)
      this.setAppState(prev => {
        const withNotice = result.interrupted
          ? consumeBridgeEvent(prev, { type: 'cancelled', content: 'Agent execution interrupted by Esc.' })
          : prev
        const withSidebar = result.sidebar ? this.applySidebarPayload(withNotice, result.sidebar) : withNotice
        return {
          ...withSidebar,
          runtime: {
            ...withSidebar.runtime,
            busy: false,
            streaming: false,
          },
        }
      })
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      this.setAppState(prev => ({
        ...appendCard(prev, 'error', 'Interrupt Failed', message, 'done'),
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
      this.flushStreamBuffer()
      const message = error instanceof Error ? error.message : String(error)
      this.setAppState(prev => ({
        ...consumeBridgeEvent(prev, { type: 'error', error: message }),
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
      const next = this.applySidebarPayload(prev, sidebar)
      return sidebarSnapshot(prev) === sidebarSnapshot(next) ? prev : next
    })
  }

  private applySidebarPayload(prev: AppState, sidebar: AppState['sidebar']): AppState {
    return {
      ...prev,
      sidebar,
      context: sidebar.context || prev.context,
      permissions: {
        ...prev.permissions,
        mode: String(sidebar.permission_mode || prev.permissions.mode),
        rules: Number(sidebar.permission_rules || prev.permissions.rules),
        pending: (sidebar.pending as typeof prev.permissions.pending) || prev.permissions.pending,
      },
      model: {
        ...prev.model,
        model: String(sidebar.model || prev.model.model),
        provider: String(sidebar.provider || prev.model.provider),
        profile: String(sidebar.profile || prev.model.profile),
      },
      session: {
        ...prev.session,
        id: String(sidebar.session_id || prev.session.id),
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
  }

  async pollRuntime(): Promise<void> {
    if (this.closing) {
      return
    }
    let result: { notices: S4BridgeEvent[]; sidebar: AppState['sidebar'] }
    try {
      result = await this.bridge.pollRuntimeNotices()
    } catch (error) {
      if (this.closing || isBridgeClosedError(error)) {
        return
      }
      throw error
    }
    if (this.closing) {
      return
    }
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
    history_cards?: Array<{ kind?: string; title?: string; body?: string; status?: string; metadata?: Record<string, unknown> }>
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
        profile: String(init.sidebar.profile || 'default'),
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
    const historyCards = init.history_cards || []
    if (historyCards.length > 0) {
      state = appendCard(
        state,
        'system',
        'Restored Transcript',
        `Loaded ${historyCards.length} history message(s) from session ${init.session_id}.`,
        'done',
      )
      for (const card of historyCards) {
        const kind = this.normalizeTranscriptKind(card.kind)
        state = appendCard(
          state,
          kind,
          card.title || 'History',
          card.body || '',
          card.status,
          card.metadata,
        )
      }
    }
    for (const notice of init.startup_notices) {
      state = appendCard(state, 'system', notice.title || 'Notice', notice.body || '', 'done')
    }
    if (init.pending?.active) {
      state = consumeBridgeEvent(state, {
        type: 'interruption',
        content: init.pending.reason || 'A pending interaction was restored with this session.',
        payload: init.pending,
      })
    }
    return state
  }

  private normalizeTranscriptKind(kind: unknown): TranscriptCardKind {
    const normalized = String(kind || 'system')
    if (['system', 'user', 'assistant', 'thinking', 'tool', 'round', 'separator', 'warning', 'error'].includes(normalized)) {
      return normalized as TranscriptCardKind
    }
    return 'system'
  }

  async close(): Promise<void> {
    this.closing = true
    try {
      this.flushStreamBuffer()
      await this.bridge.close()
    } finally {
      this.clearStreamTimer()
      if (this.paletteTimer) {
        clearTimeout(this.paletteTimer)
        this.paletteTimer = null
      }
      this.bridge.terminate()
    }
  }
}
