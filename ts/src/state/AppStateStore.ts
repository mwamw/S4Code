import type { ContextPayload, PendingPayload, SidebarPayload } from '@/types/bridge'

export type TranscriptCardKind =
  | 'system'
  | 'user'
  | 'assistant'
  | 'thinking'
  | 'tool'
  | 'round'
  | 'separator'
  | 'warning'
  | 'error'

export type TranscriptCard = {
  id: string
  kind: TranscriptCardKind
  title: string
  body: string
  status?: string
  metadata?: Record<string, unknown>
}

export type TaskEntry = {
  id: string
  status: string
  title: string
  kind: 'structured' | 'background'
}

export type PaletteEntry = {
  name: string
  description: string
  argumentHint?: string
}

export type AppState = {
  session: {
    id: string
    title: string
    restored: boolean
    dirty: boolean
    checkpointCount: number
  }
  project: {
    cwd: string
    root: string
    projectName: string
    branch: string
  }
  model: {
    model: string
    provider: string
    profile: string
  }
  permissions: {
    mode: string
    rules: number
    pending: PendingPayload | null
  }
  context: ContextPayload
  runtime: {
    busy: boolean
    streaming: boolean
    renderMode: 'interactive' | 'oneshot'
    autoFollowTranscript: boolean
    currentRound: number | null
    recentNotices: string[]
  }
  transcript: {
    committedCards: TranscriptCard[]
    liveRoundCard?: TranscriptCard
    liveThinkingCard?: TranscriptCard
    liveAssistantCard?: TranscriptCard
    liveToolCards: Record<string, TranscriptCard>
    streamFlushAt?: number
    cards: TranscriptCard[]
    currentRoundCardId?: string
    currentThinkingCardId?: string
    currentAssistantCardId?: string
    toolCardIds: Record<string, string>
    lastRoundMetrics?: Record<string, unknown>
  }
  tasks: {
    items: Record<string, TaskEntry>
  }
  skills: {
    active: string[]
    queued: string[]
  }
  mcp: {
    enabled: boolean
    configured: number
    connected: number
    disabled: number
    unavailable: number
  }
  sidebar: SidebarPayload
  palette: {
    recentCommands: string[]
    entries: PaletteEntry[]
    selection: number
  }
  ui: {
    sidebarVisible: boolean
    theme: string
    input: string
  }
}

export function getDefaultAppState(): AppState {
  return {
    session: {
      id: '',
      title: 'S4Code session',
      restored: false,
      dirty: false,
      checkpointCount: 0,
    },
    project: {
      cwd: '',
      root: '',
      projectName: 'S4Code',
      branch: '-',
    },
    model: {
      model: '-',
      provider: '-',
      profile: 'default',
    },
    permissions: {
      mode: 'default',
      rules: 0,
      pending: null,
    },
    context: {
      usage_percent: '-',
      usage_bar: '[----------------]',
    },
    runtime: {
      busy: false,
      streaming: false,
      renderMode: 'interactive',
      autoFollowTranscript: true,
      currentRound: null,
      recentNotices: [],
    },
    transcript: {
      committedCards: [],
      liveToolCards: {},
      cards: [],
      toolCardIds: {},
    },
    tasks: {
      items: {},
    },
    skills: {
      active: [],
      queued: [],
    },
    mcp: {
      enabled: false,
      configured: 0,
      connected: 0,
      disabled: 0,
      unavailable: 0,
    },
    sidebar: {},
    palette: {
      recentCommands: [],
      entries: [],
      selection: 0,
    },
    ui: {
      sidebarVisible: false,
      theme: 's4',
      input: '',
    },
  }
}
