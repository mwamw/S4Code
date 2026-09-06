/** Ink-only interaction/presentation over the shared, UI-free BridgeClient. */
import { BridgeClient, BridgeError, type InteractionRequest, type RunEvent, type SessionInfo } from '../../packages/bridge-client/src/index'
import type { ContextPayload, ExecuteCommandPayload, InitPayload, PendingPayload, S4BridgeEvent, SidebarPayload } from '../types/bridge'
import type { CommandChoice, CommandChoiceSource } from '../types/command'
import { Checkpoints } from './Checkpoints'

type CoreContext = { estimatedRequestTokens?: number; maxTokens?: number | null }
type State = SessionInfo & { project_name: string; branch: string; permission_mode: string; context: CoreContext; pending: InteractionRequest | null; startup_issues: string[];
  profile?: string; permission_rules?: number; skills?: { active: string[] }; deferred_tools?: SidebarPayload['deferred_tools'];
  processes?: Array<{ task_id: string; status: string; return_code?: number | null }>;
  mcp?: { enabled: boolean; servers: Array<{ enabled: boolean; registered: boolean; connection?: { status?: string } }> } }
const pretty = (value: unknown): string => typeof value === 'string' ? value : JSON.stringify(value, null, 2)
export const isBridgeClosedError = (error: unknown): boolean => error instanceof BridgeError && ['closed', 'disconnected'].includes(error.code)

export class InkCoreClient {
  private sessionId?: string
  private currentRound = 0
  private initialized = false
  private interaction: InteractionRequest | null = null
  private queuedSkills: string[] = []
  private processStates = new Map<string, string>()
  private submission: { cancelled: boolean; finished: Promise<void> } | null = null
  readonly checkpoints: Checkpoints
  constructor(private transport: BridgeClient) {
    this.checkpoints = new Checkpoints(<T>(method: string, params = {}) => this.callCore<T>(method, params))
  }
  callCore<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    return this.transport.request(method, { session_id: this.sessionId, ...params })
  }
  private inspect<T>(topic: string, target?: unknown): Promise<T> {
    return this.callCore('core.inspect', { topic, ...(typeof target === 'string' && target ? { target } : {}) })
  }
  private pendingView(pending: InteractionRequest | null): PendingPayload {
    this.interaction = pending
    return pending ? { ...pending.details, active: true, title: pending.kind, tool_name: pending.tool_name,
      interaction_type: pending.kind, reason: pretty(pending.arguments) } : { active: false }
  }
  private sidebar(state: State): SidebarPayload {
    const servers = state.mcp?.servers || []
    const processes = state.processes || []
    return { project_name: state.project_name, branch: state.branch, model: state.model, provider: state.provider,
      session_id: state.session_id, permission_mode: state.permission_mode, profile: state.profile, permission_rules: state.permission_rules,
      context: this.context(state.context), deferred_tools: state.deferred_tools,
      pending: this.pendingView(state.pending), skills: { active: state.skills?.active || [], queued: [...this.queuedSkills] },
      background_tasks: processes, active_background_count: processes.filter(item => item.status === 'running').length,
      failed_background_count: processes.filter(item => item.status === 'failed' || (item.return_code != null && item.return_code !== 0)).length,
      mcp: { enabled: state.mcp?.enabled ?? false, configured: servers.length,
        connected: servers.filter(server => server.connection?.status === 'connected').length,
        disabled: servers.filter(server => !server.enabled).length,
        unavailable: servers.filter(server => server.enabled && (!server.registered || server.connection?.status !== 'connected')).length } }
  }
  private context(context: CoreContext): ContextPayload {
    const used = context.estimatedRequestTokens
    const max = context.maxTokens
    const ratio = used != null && max != null && max > 0 ? used / max : null
    const filled = ratio == null ? 0 : Math.max(0, Math.min(20, Math.round(ratio * 20)))
    return { used_tokens: used, estimated_request_tokens: used, max_tokens: max,
      remaining_tokens: used != null && max != null ? Math.max(0, max - used) : null,
      usage_ratio: ratio, usage_percent: ratio == null ? null : `${(ratio * 100).toFixed(1)}%`,
      usage_bar: `[${'#'.repeat(filled)}${'-'.repeat(20 - filled)}]` }
  }
  async init(): Promise<InitPayload> {
    if (!this.initialized) {
      this.sessionId = (await this.transport.initialize()).session_id
      this.initialized = true
    }
    const state = await this.callCore<State>('core.state')
    const history = await this.inspect<Array<{ role: string; text: string }>>('history')
    const restore = await this.inspect<Record<string, unknown>>('restore')
    await this.checkpoints.load(state.session_id)
    return { cwd: state.project_root, session_id: state.session_id, project_name: state.project_name,
      project_root: state.project_root, branch: state.branch || '', model: state.model, provider: state.provider,
      permission_mode: state.permission_mode, welcome: { title: 'S4Code', body: 'Use /help to explore commands.' },
      startup_notices: state.startup_issues.map(body => ({ title: 'Startup', body })),
      history_cards: history.map(item => ({ kind: item.role === 'user' ? 'user' : 'assistant', title: item.role, body: item.text, status: 'done' })),
      sidebar: this.sidebar(state), context: this.context(state.context), pending: this.pendingView(state.pending),
      restore }
  }
  async getSidebar(_force = false): Promise<SidebarPayload> { return this.sidebar(await this.callCore<State>('core.state')) }
  async getContextPanel(): Promise<ContextPayload> { return this.context(await this.inspect<CoreContext>('context')) }
  async getPending(): Promise<PendingPayload> { return this.pendingView(await this.callCore('core.interaction.pending')) }
  async getCommandChoices(source: CommandChoiceSource): Promise<CommandChoice[]> {
    if (source === 'models') {
      const models = await this.inspect<Array<{ name: string; model: string; provider: string; active: boolean }>>('models')
      return models.map(model => ({ value: model.name, description: `${model.provider}/${model.model}`, active: model.active }))
    }
    if (source === 'sessions') {
      const sessions = await this.callCore<Array<{ session_id: string; title: string }>>('core.session.list')
      return sessions.map(session => ({ value: session.session_id, label: session.title || session.session_id,
        description: session.session_id, active: session.session_id === this.sessionId }))
    }
    if (source === 'checkpoints') {
      return this.checkpoints.list().slice().reverse().map(checkpoint => ({ value: checkpoint.checkpoint_id,
        label: checkpoint.label, description: `${checkpoint.checkpoint_id} · ${checkpoint.created_at}` }))
    }
    const skills = await this.inspect<Array<{ name: string; description: string }>>('skills')
    return skills.map(skill => ({ value: skill.name, description: skill.description }))
  }
  buildPrompt(kind: string, params: Record<string, unknown> = {}): Promise<{ prompt: string }> { return this.callCore('core.workflow', { kind, ...params }) }
  async renderView(view: string, params: Record<string, unknown> = {}): Promise<{ title: string; text: string; payload?: unknown }> {
    let payload: unknown
    if (['session_checkpoints', 'session_timeline'].includes(view)) payload = this.checkpoints.list()
    else if (['sessions', 'session_tree'].includes(view)) payload = await this.callCore('core.session.list')
    else if (view === 'pending') payload = await this.getPending()
    else if (view === 'tasks') payload = { tasks: await this.inspect('tasks'), processes: await this.inspect('processes') }
    else if (view === 'runtime') payload = { state: await this.callCore('core.state'), tasks: await this.inspect('tasks'), agents: await this.inspect('agents') }
    else if (view === 'task_output') payload = await this.callCore('core.runtime.action', { action: 'task.output', arguments: { task_id: params.task_id, block: false } })
    else if (view === 'agent_detail') payload = await this.inspect('agent', params.agent_id)
    else {
      const topics: Record<string, string> = { status: 'state', session: 'state', doctor: 'diagnostics', task_detail: 'task',
        permission_history: 'permissions', mcp_server: 'mcp', mcp_tools: 'mcp', mcp_resources: 'mcp' }
      payload = await this.inspect(topics[view] || view, params.target || params.task_id || params.server_name)
    }
    return { title: view.replaceAll('_', ' '), text: pretty(payload), payload }
  }
  async executeCommand(text: string): Promise<ExecuteCommandPayload> {
    const [name, ...tokens] = text.trim().slice(1).split(/\s+/)
    const arg = tokens.join(' ')
    const result: ExecuteCommandPayload = { handled: true, command_name: name }
    if (['exit', 'quit', 'q'].includes(name)) return { ...result, exit_requested: true }
    if (['sidebar', 'theme', 'themes'].includes(name)) return { ...result, message: `${name}: ${arg || 'current'}` }
    if (name === 'copy') return { ...result, metadata: { ui_action: 'copy_to_clipboard', copy_target: arg || 'transcript' } }
    if (name === 'plan') { await this.callCore('core.plan.set', { enabled: arg !== 'off' }); return { ...result, message: `Plan mode ${arg || 'on'}` } }
    if (name === 'checkpoint') return { ...result, message: `Created ${await this.checkpoints.create(arg || 'Manual checkpoint')}` }
    if (name === 'resume' && arg) return { ...result, ...(await this.runAction('load_session', { session_id: arg })) }
    if (name === 'config') return { ...result, message: pretty(await this.inspect('configuration')) }
    if (['files', 'hooks'].includes(name)) return { ...result, message: pretty(await this.inspect(name, arg)) }
    if (name === 'resume') return { ...result, message: pretty(await this.callCore('core.session.list')) }
    throw new Error(`Unknown local command: /${name}`)
  }
  async runAction(action: string, params: Record<string, unknown> = {}): Promise<{ text: string; init?: InitPayload }> {
    if (action === 'load_session') {
      const info = await this.callCore<SessionInfo>('core.session.open', { session_id: params.session_id })
      const previous = this.sessionId
      const previousSkills = this.queuedSkills
      this.sessionId = info.session_id
      this.queuedSkills = []
      try { const init = await this.init(); this.processStates.clear(); return { text: `Loaded ${info.session_id}`, init } }
      catch (error) { this.sessionId = previous; this.queuedSkills = previousSkills; throw error }
    }
    if (action === 'fork_session') {
      const info = await this.callCore<SessionInfo>('core.session.fork', { title: params.title })
      return this.runAction('load_session', { session_id: info.session_id })
    }
    if (action === 'rewind_session') { await this.checkpoints.rewind(String(params.target || 'last')); return { text: 'Conversation restored; workspace files were not changed.', init: await this.init() } }
    if (action === 'clear_history') { await this.callCore('core.conversation.clear'); return { text: 'Conversation cleared.', init: await this.init() } }
    if (action === 'queue_skill') {
      const name = String(params.name || '')
      const skills = await this.inspect<Array<{ name: string }>>('skills')
      if (!skills.some(item => item.name === name)) throw new Error(`Unknown skill: ${name}`)
      if (!this.queuedSkills.includes(name)) this.queuedSkills.push(name)
      return { text: `Queued skill: ${name}` }
    }
    if (action === 'clear_turn_skills') { this.queuedSkills = []; return { text: 'Queued skills cleared' } }
    const operations: Record<string, [string, Record<string, unknown>]> = {
      set_model: ['core.model.select', { target: params.target }], compact_history: ['core.context.compact', { max_tokens: params.max_tokens }],
      rename_session: ['core.session.save', { title: params.title }],
      set_permission_mode: ['core.permissions.mode', { mode: params.mode }], clear_permissions: ['core.permissions.clear', { source: params.source || 'session' }],
      stop_task: ['core.runtime.action', { action: 'task.stop', arguments: { task_id: params.task_id } }],
      enter_worktree: ['core.runtime.action', { action: 'worktree.enter', arguments: { name: params.name } }],
      exit_worktree: ['core.runtime.action', { action: 'worktree.exit', arguments: params }],
    }
    if (['connect_mcp', 'disconnect_mcp', 'refresh_mcp'].includes(action)) operations[action] = ['core.mcp.action', { action: action.replace('_mcp', ''), server_name: params.server_name }]
    if (action === 'permission_rule') {
      const matcher: Record<string, unknown> = {}
      let source = 'session'
      const keys: Record<string, string> = { path: 'path_prefixes', paths: 'path_prefixes', command: 'command_prefixes', cmd: 'command_prefixes', host: 'hosts', hosts: 'hosts', mcp: 'mcp_servers', server: 'mcp_servers', risk: 'risk_categories', risks: 'risk_categories' }
      for (const token of (params.tokens || []) as string[]) {
        const index = token.indexOf('='); if (index < 0) throw new Error(`Expected key=value: ${token}`)
        const key = token.slice(0, index), value = token.slice(index + 1)
        if (key === 'source') source = value
        else if (keys[key]) matcher[keys[key]] = value.split(',').filter(Boolean)
        else if (key.startsWith('equals:') || key.startsWith('contains:')) {
          const field = key.startsWith('equals:') ? 'param_equals' : 'param_contains'
          matcher[field] = { ...(matcher[field] as object || {}), [key.slice(key.indexOf(':') + 1)]: value }
        } else throw new Error(`Unknown permission matcher: ${key}`)
      }
      operations[action] = ['core.permissions.add', { rule: { behavior: params.behavior, tool_name: params.tool_name, source, matcher } }]
    }
    const operation = operations[action]
    if (!operation) throw new Error(`Unknown action: ${action}`)
    return { text: pretty(await this.callCore(operation[0], operation[1])) }
  }
  private translate(event: RunEvent): S4BridgeEvent {
    const base = { invocation_id: event.run_id, sequence: event.sequence }
    if (event.type === 'reasoning_delta') return { ...base, type: 'thinking_delta', delta: event.content }
    if (event.type === 'text_delta') return { ...base, type: 'text_delta', delta: event.content }
    if (event.type === 'final') return { ...base, type: 'agent_final' }
    if (event.type === 'round_start') {
      this.currentRound = Number(event.data.round)
      return { ...base, type: 'round_start', round: this.currentRound }
    }
    if (event.type === 'usage') {
      const stats = (event.data.stats || {}) as Record<string, unknown>
      const llm = (event.data.llm_invokes || []) as Array<{ stats: Record<string, unknown> }>
      return { ...base, type: 'round_metrics', round: this.currentRound,
        metrics: { ...stats, llm_requests: stats.llm_calls,
          llm_duration_ms: llm.reduce((total, item) => total + Number(item.stats.duration_ms || 0), 0) } }
    }
    if (event.type === 'compaction_start') return { ...base, type: 'system_notice', title: 'Context',
      content: `Compacting history (tokens=${event.data.tokens_before}, budget=${event.data.max_tokens}).` }
    if (event.type === 'compaction_result') return { ...base, type: 'system_notice', title: 'Context',
      content: event.data.was_compacted ? `History compacted: ${event.data.tokens_before} -> ${event.data.tokens_after}.` : 'History compaction finished without changes.' }
    if (event.type === 'error' && event.data.interrupted) return { ...base, type: 'run_paused' }
    if (event.type === 'tool_call' || event.type === 'tool_result') {
      const result = (event.data.result || {}) as Record<string, unknown>
      return { ...base, ...result, type: event.type, tool_name: event.data.tool_name, tool_id: event.data.tool_call_id,
        tool_args: event.data.arguments, content: event.content, status: event.data.status || result.status }
    }
    if (event.type === 'run_finished') {
      if (event.data.status === 'interaction_required') {
        const interaction = event.data.interaction as InteractionRequest
        this.interaction = interaction
        return { ...base, type: 'interruption', content: 'Approval or answer required.',
          payload: { interaction_id: interaction.interaction_id, tool_name: interaction.tool_name,
            tool_args: interaction.arguments, metadata: { ...interaction.details, interaction_type: interaction.kind } } }
      }
      if (event.data.status === 'failed') return { ...base, type: 'run_failed' }
      if (event.data.status === 'cancelled') return { ...base, type: 'cancelled', content: 'Run cancelled' }
      return { ...base, type: 'final', content: event.data.text }
    }
    return { ...base, type: event.type, content: event.content, ...event.data }
  }
  submitPrompt(prompt: string, onEvent: (event: S4BridgeEvent) => void): Promise<{ done: boolean; sidebar: SidebarPayload }> {
    return this.runSubmission(prompt, onEvent)
  }
  private async runSubmission(prompt: string, onEvent: (event: S4BridgeEvent) => void, prepare?: () => Promise<void>): Promise<{ done: boolean; sidebar: SidebarPayload }> {
    if (this.submission) throw new Error('A submission is already in progress')
    let finish!: () => void
    const submission = { cancelled: false, finished: new Promise<void>(resolve => { finish = resolve }) }
    this.submission = submission
    const cancelled = async () => {
      onEvent({ type: 'cancelled', content: 'Submission cancelled' })
      return { done: false, sidebar: await this.getSidebar() }
    }
    try {
      if (prepare) await prepare()
      if (submission.cancelled) return await cancelled()
      this.currentRound = 0
      await this.checkpoints.create('Before prompt')
      if (submission.cancelled) return await cancelled()
      onEvent({ type: 'checkpoint', checkpoint: { ...this.checkpoints.list().at(-1), reason: 'before_prompt' } })
      for (const name of this.queuedSkills) {
        if (submission.cancelled) return await cancelled()
        await this.callCore('core.skill.activate', { name })
      }
      if (submission.cancelled) return await cancelled()
      this.queuedSkills = []
      const result = await this.transport.stream({ session_id: this.sessionId, prompt }, event => onEvent(this.translate(event)))
      await this.checkpoints.create(result.status === 'interaction_required' ? 'Paused prompt' : result.status === 'cancelled' ? 'Cancelled prompt' : 'After prompt')
      onEvent({ type: 'checkpoint', checkpoint: { ...this.checkpoints.list().at(-1),
        reason: result.status === 'interaction_required' ? 'interruption' : 'after_prompt' } })
      return { done: !submission.cancelled && result.status === 'completed', sidebar: await this.getSidebar() }
    } finally {
      this.submission = null
      finish()
    }
  }
  async resolvePending(action: 'approve' | 'deny' | 'answer', answer: string, onEvent: (event: S4BridgeEvent) => void): Promise<{ done: boolean; sidebar: SidebarPayload }> {
    if (!this.interaction) throw new Error('No pending interaction')
    const interaction = this.interaction
    return this.runSubmission('Continue after the resolved interaction.', onEvent, async () => {
      await this.callCore('core.interaction.respond', { interaction_id: interaction.interaction_id, action, answer })
      this.interaction = null
    })
  }
  async interrupt(reason = 'User cancelled the run'): Promise<{ interrupted: boolean; active_streams: number; sidebar: SidebarPayload }> {
    const submission = this.submission
    if (submission) submission.cancelled = true
    const result = await this.callCore<{ stop_requested: boolean }>('core.stop', { reason })
    await submission?.finished
    return { interrupted: Boolean(submission) || result.stop_requested, active_streams: 0, sidebar: await this.getSidebar() }
  }
  async pollRuntimeNotices(): Promise<{ notices: S4BridgeEvent[]; sidebar: SidebarPayload }> {
    const state = await this.callCore<State>('core.state')
    const processes = state.processes || []
    const notices: S4BridgeEvent[] = []
    for (const item of processes) {
      const previous = this.processStates.get(item.task_id)
      if (previous && previous !== item.status) notices.push({ type: 'system_notice', title: 'Background task',
        content: `${item.task_id}: ${item.status}${item.return_code != null ? ` (exit ${item.return_code})` : ''}` })
      this.processStates.set(item.task_id, item.status)
    }
    const ids = new Set(processes.map(item => item.task_id))
    for (const id of this.processStates.keys()) if (!ids.has(id)) this.processStates.delete(id)
    return { notices, sidebar: this.sidebar(state) }
  }
  async close(): Promise<{ closed: boolean }> {
    if (this.submission) this.submission.cancelled = true
    await this.transport.close()
    return { closed: true }
  }
  terminate(): void { this.transport.terminate() }
}
