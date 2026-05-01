import type { QueryEngine } from '@/query/QueryEngine'

export type CommandResultDisplay = 'system' | 'user' | 'skip'

export type CommandBase = {
  name: string
  description: string
  aliases?: string[]
  argumentHint?: string
  category?: 'core' | 'workspace' | 'session' | 'runtime' | 'approval' | 'debug'
  keywords?: string[]
  priority?: number
  kind?: 'workflow'
  immediate?: boolean
  isSensitive?: boolean
}

export type PromptCommand = CommandBase & {
  type: 'prompt'
  progressMessage: string
  getPrompt: (args: string, engine: QueryEngine) => Promise<string>
}

export type LocalCommand = CommandBase & {
  type: 'local'
  run: (args: string, engine: QueryEngine) => Promise<void | 'quit'>
}

export type LocalJSXCommand = CommandBase & {
  type: 'local-jsx'
  run: (args: string, engine: QueryEngine) => Promise<void | 'quit'>
}

export type Command = PromptCommand | LocalCommand | LocalJSXCommand

export type CommandInvocation = {
  command: Command
  args: string
  matchedName: string
}
