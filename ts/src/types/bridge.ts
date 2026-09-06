export type BridgeEnvelope =
  | BridgeResponseEnvelope
  | BridgeEventEnvelope

export type BridgeResponseEnvelope = {
  request_id: string
  type: 'response'
  ok: boolean
  result?: unknown
  error?: BridgeErrorPayload
}

export type BridgeErrorPayload = {
  type?: string
  message?: string
  reason: string
  impact: string
  next_step: string
  debug?: string
}

export type BridgeEventEnvelope = {
  request_id: string
  type: 'event'
  event: S4BridgeEvent
}

export type S4BridgeEvent = {
  type: string
  [key: string]: unknown
}

export type BridgeRequest = {
  request_id: string
  method: string
  params?: Record<string, unknown>
}

export type InitPayload = {
  cwd: string
  session_id: string
  project_name: string
  project_root: string
  branch: string
  model: string
  provider: string
  permission_mode: string
  welcome: {
    kind?: string
    title?: string
    body?: string
  }
  history_cards?: Array<{
    kind?: string
    title?: string
    body?: string
    status?: string
    metadata?: Record<string, unknown>
  }>
  startup_notices: Array<{
    kind?: string
    title?: string
    body?: string
  }>
  sidebar: SidebarPayload
  context: ContextPayload
  restore: Record<string, unknown>
  pending: PendingPayload
}

export type SidebarPayload = {
  project_name?: string
  branch?: string
  model?: string
  provider?: string
  profile?: string
  session_id?: string
  permission_mode?: string
  permission_rules?: number
  worktree?: Record<string, unknown>
  skills?: {
    active?: string[]
    queued?: string[]
  }
  deferred_tools?: {
    total?: number
    loaded?: number
    pending_schema?: number
    immediate?: number
  }
  mcp?: {
    enabled?: boolean
    configured?: number
    connected?: number
    disabled?: number
    unavailable?: number
  }
  background_tasks?: Array<Record<string, unknown>>
  active_background_count?: number
  failed_background_count?: number
  context?: ContextPayload
  pending?: PendingPayload
  restore?: Record<string, unknown>
}

export type ContextPayload = {
  used_tokens?: number | null
  max_tokens?: number | null
  remaining_tokens?: number | null
  estimated_request_tokens?: number | null
  usage_ratio?: number | null
  usage_percent?: string | null
  usage_bar?: string | null
  history_budget_tokens?: number | null
  history_tokens?: number | null
  cache?: Record<string, unknown>
  compaction?: Record<string, unknown>
}

export type PendingPayload = {
  active?: boolean
  title?: string
  tool_name?: string | null
  reason?: string | null
  interaction_type?: string
  risk_level?: string
  reversible?: boolean
  affects_shared_state?: boolean
  overwrites_local_changes?: boolean
  remember_supported?: boolean
}

export type ExecuteCommandPayload = {
  handled: boolean
  command_name?: string | null
  message?: string | null
  should_query?: boolean
  query?: string | null
  exit_requested?: boolean
  refresh_requested?: boolean
  metadata?: Record<string, unknown>
  session_id?: string
  sidebar?: SidebarPayload
  init?: InitPayload
}
