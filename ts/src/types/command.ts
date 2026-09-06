import type { InkController } from '@/controller/InkController'

export type CommandResultDisplay = 'system' | 'user' | 'skip'

export type CommandChoiceSource = 'models' | 'sessions' | 'checkpoints' | 'skills'

export type CommandChoice = {
  value: string
  label?: string
  description: string
  active?: boolean
}

export type CommandBase = {
  name: string
  description: string
  aliases?: string[]
  argumentHint?: string
  argumentSource?: CommandChoiceSource
  argumentChoices?: CommandChoice[]
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
  getPrompt: (args: string, engine: InkController) => Promise<string>
}

export type LocalCommand = CommandBase & {
  type: 'local'
  run: (args: string, engine: InkController) => Promise<void | 'quit'>
}

export type LocalJSXCommand = CommandBase & {
  type: 'local-jsx'
  run: (args: string, engine: InkController) => Promise<void | 'quit'>
}

export type Command = PromptCommand | LocalCommand | LocalJSXCommand

export type CommandInvocation = {
  command: Command
  args: string
  matchedName: string
}
