import type { Command, CommandInvocation, LocalCommand, PromptCommand } from '../types/command'
import type { QueryEngine } from '../query/QueryEngine'
import type { AppState } from '../state/AppStateStore'

function viewCommand(
  name: string,
  description: string,
  view: string,
  argumentHint?: string,
  extra: Partial<LocalCommand> = {},
): LocalCommand {
  return {
    type: 'local',
    name,
    description,
    argumentHint,
    ...extra,
    run: async (args, engine) => {
      await engine.showView(view, args)
    },
  }
}

export function getCommands(): Command[] {
  return [
    {
      type: 'local',
      name: 'help',
      description: 'Show command help and recommended workflows.',
      category: 'core',
      aliases: ['?'],
      priority: 100,
      run: async (_args, engine) => {
        await engine.showHelp()
      },
    },
    {
      type: 'local',
      name: 'quit',
      description: 'Exit S4Code.',
      category: 'core',
      aliases: ['exit', 'q'],
      priority: 99,
      immediate: true,
      run: async () => 'quit',
    },
    viewCommand('status', 'Show current workspace and runtime status.', 'status', undefined, { category: 'core', priority: 95 }),
    viewCommand('context', 'Show context usage and budget.', 'context', undefined, { category: 'runtime', aliases: ['ctx'], priority: 90 }),
    viewCommand('cost', 'Show usage, cost, and cache information.', 'cost', undefined, { category: 'runtime', priority: 50 }),
    viewCommand('trace', 'Show recent turn summaries.', 'trace', undefined, { category: 'debug', priority: 20 }),
    viewCommand('tools', 'Show available tools and their availability.', 'tools', undefined, { category: 'runtime', priority: 70 }),
    viewCommand('skills', 'Show active and queued skills.', 'skills', undefined, { category: 'runtime', priority: 75 }),
    {
      type: 'local',
      name: 'skills queue',
      description: 'Queue a skill for the next turn.',
      argumentHint: '<skill-name>',
      category: 'runtime',
      priority: 76,
      run: async (args, engine) => {
        await engine.queueSkill(args)
      },
    },
    {
      type: 'local',
      name: 'skills clear',
      description: 'Clear skills queued for the next turn.',
      category: 'runtime',
      priority: 76,
      run: async (_args, engine) => {
        await engine.clearTurnSkills()
      },
    },
    viewCommand('worktree', 'Show current worktree state.', 'worktree', undefined, { category: 'workspace', priority: 75 }),
    {
      type: 'local',
      name: 'worktree enter',
      description: 'Enter a managed worktree.',
      argumentHint: '[name]',
      category: 'workspace',
      priority: 74,
      immediate: true,
      run: async (args, engine) => {
        await engine.enterWorktree(args)
      },
    },
    {
      type: 'local',
      name: 'worktree exit',
      description: 'Exit the current managed worktree.',
      argumentHint: '[keep|remove] [discard]',
      category: 'workspace',
      priority: 74,
      immediate: true,
      isSensitive: true,
      run: async (args, engine) => {
        await engine.exitWorktree(args)
      },
    },
    viewCommand('restore', 'Show restore continuity information.', 'restore', undefined, { category: 'session', priority: 65 }),
    viewCommand('pending', 'Show pending approval or question state.', 'pending', undefined, { category: 'approval', priority: 100 }),
    viewCommand('tasks', 'Show structured and background tasks.', 'tasks', undefined, { category: 'runtime', priority: 80 }),
    viewCommand('mcp', 'Show MCP server status.', 'mcp', undefined, { category: 'runtime', priority: 35 }),
    viewCommand('mcp server', 'Show one MCP server detail.', 'mcp_server', '<server-name>', { category: 'runtime', priority: 35 }),
    viewCommand('mcp tools', 'Show tools for one MCP server.', 'mcp_tools', '<server-name>', { category: 'runtime', priority: 35 }),
    viewCommand('mcp resources', 'Show resources for one MCP server.', 'mcp_resources', '<server-name>', { category: 'runtime', priority: 35 }),
    {
      type: 'local',
      name: 'mcp refresh',
      description: 'Refresh MCP server connections.',
      argumentHint: '[server-name]',
      category: 'runtime',
      priority: 35,
      run: async (args, engine) => {
        await engine.runMcpAction('refresh_mcp', args)
      },
    },
    {
      type: 'local',
      name: 'mcp connect',
      description: 'Connect MCP servers.',
      argumentHint: '[server-name]',
      category: 'runtime',
      priority: 35,
      run: async (args, engine) => {
        await engine.runMcpAction('connect_mcp', args)
      },
    },
    {
      type: 'local',
      name: 'mcp disconnect',
      description: 'Disconnect MCP servers.',
      argumentHint: '[server-name]',
      category: 'runtime',
      priority: 35,
      run: async (args, engine) => {
        await engine.runMcpAction('disconnect_mcp', args)
      },
    },
    viewCommand('agents', 'Show active subagents.', 'agents', undefined, { category: 'runtime', priority: 64 }),
    viewCommand('agent', 'Show one subagent by id.', 'agent_detail', '<agent-id>', { category: 'runtime', priority: 63 }),
    {
      type: 'local',
      name: 'task',
      description: 'Show one task by id.',
      argumentHint: '<task-id>',
      category: 'runtime',
      priority: 65,
      run: async (args, engine) => {
        await engine.showTaskDetail(args)
      },
    },
    {
      type: 'local',
      name: 'task output',
      description: 'Show task output.',
      argumentHint: '<task-id>',
      category: 'runtime',
      priority: 85,
      run: async (args, engine) => {
        await engine.showTaskOutput(args)
      },
    },
    {
      type: 'local',
      name: 'task stop',
      description: 'Stop a running task.',
      argumentHint: '<task-id>',
      category: 'runtime',
      priority: 85,
      immediate: true,
      run: async (args, engine) => {
        await engine.stopTask(args)
      },
    },
    {
      type: 'local',
      name: 'session list',
      description: 'List saved sessions.',
      category: 'session',
      aliases: ['sessions'],
      priority: 70,
      run: async (_args, engine) => {
        await engine.showView('sessions', '')
      },
    },
    viewCommand('session', 'Show the current session details.', 'session', undefined, { category: 'session', priority: 72 }),
    viewCommand('session show', 'Show the current session details.', 'session', undefined, { category: 'session', priority: 72 }),
    viewCommand('session checkpoints', 'List restorable checkpoints.', 'session_checkpoints', undefined, { category: 'session', priority: 71 }),
    viewCommand('session timeline', 'Show checkpoint and trace timeline.', 'session_timeline', undefined, { category: 'session', priority: 71 }),
    viewCommand('session tree', 'Show session fork and restore tree.', 'session_tree', undefined, { category: 'session', priority: 71 }),
    {
      type: 'local',
      name: 'session load',
      description: 'Load a saved session.',
      argumentHint: '<session-id>',
      category: 'session',
      aliases: ['resume'],
      priority: 70,
      immediate: true,
      run: async (args, engine) => {
        await engine.loadSession(args)
      },
    },
    {
      type: 'local',
      name: 'session restore',
      description: 'Restore a saved session.',
      argumentHint: '<session-id>',
      category: 'session',
      aliases: ['restore-session'],
      priority: 70,
      immediate: true,
      run: async (args, engine) => {
        await engine.loadSession(args)
      },
    },
    {
      type: 'local',
      name: 'session rewind',
      description: 'Rewind to a checkpoint.',
      argumentHint: '<checkpoint-id|index|last>',
      category: 'session',
      priority: 69,
      immediate: true,
      isSensitive: true,
      run: async (args, engine) => {
        await engine.rewindSession(args)
      },
    },
    {
      type: 'local',
      name: 'session fork',
      description: 'Fork the current session.',
      argumentHint: '[title]',
      category: 'session',
      priority: 68,
      immediate: true,
      run: async (args, engine) => {
        await engine.forkSession(args)
      },
    },
    {
      type: 'local',
      name: 'session rename',
      description: 'Rename the current session.',
      argumentHint: '<title>',
      category: 'session',
      priority: 68,
      run: async (args, engine) => {
        await engine.renameSession(args)
      },
    },
    {
      type: 'local',
      name: 'confirm',
      description: 'Approve the pending interaction.',
      argumentHint: '[note]',
      category: 'approval',
      priority: 100,
      immediate: true,
      run: async (args, engine) => {
        await engine.resolvePending('approve', args)
      },
    },
    {
      type: 'local',
      name: 'deny',
      description: 'Deny the pending interaction.',
      argumentHint: '[reason]',
      category: 'approval',
      priority: 98,
      immediate: true,
      run: async (args, engine) => {
        await engine.resolvePending('deny', args)
      },
    },
    {
      type: 'local',
      name: 'answer',
      description: 'Answer the pending interaction.',
      argumentHint: '<text>',
      category: 'approval',
      priority: 96,
      immediate: true,
      run: async (args, engine) => {
        await engine.resolvePending('answer', args)
      },
    },
    {
      type: 'local',
      name: 'model',
      description: 'Switch the active model profile or literal model.',
      argumentHint: '<profile-or-model>',
      category: 'runtime',
      priority: 40,
      run: async (args, engine) => {
        await engine.setModel(args)
      },
    },
    {
      type: 'local',
      name: 'permissions',
      description: 'Show or update permission mode and rules.',
      argumentHint: '[mode|allow|deny|ask|clear|history] ...',
      category: 'approval',
      priority: 60,
      run: async (args, engine) => {
        await engine.updatePermission(args)
      },
    },
    viewCommand('models', 'Show configured model profiles.', 'models', undefined, { category: 'runtime', priority: 41 }),
    {
      type: 'local',
      name: 'compact',
      description: 'Compact conversation history.',
      argumentHint: '[max-tokens]',
      category: 'runtime',
      priority: 55,
      run: async (args, engine) => {
        await engine.compactHistory(args)
      },
    },
    {
      type: 'local',
      name: 'clear',
      description: 'Clear conversation history.',
      category: 'runtime',
      priority: 35,
      isSensitive: true,
      run: async (_args, engine) => {
        await engine.runActionCard('History', 'clear_history')
      },
    },
    {
      type: 'local',
      name: 'diff',
      description: 'Show the current git diff or a target diff.',
      argumentHint: '[target]',
      category: 'workspace',
      priority: 85,
      run: async (args, engine) => {
        await engine.showDiff(args)
      },
    },
    {
      type: 'prompt',
      name: 'review',
      description: 'Ask S4Code to review the current diff or a target.',
      argumentHint: '[target]',
      kind: 'workflow',
      category: 'workspace',
      priority: 80,
      progressMessage: 'Running review',
      getPrompt: async (args, engine) => {
        const { prompt } = await engine.bridge.buildPrompt('review', {
          target: args.trim() || undefined,
        })
        return prompt
      },
    },
    {
      type: 'local',
      name: 'doctor',
      description: 'Show a raw diagnostic dump.',
      category: 'debug',
      priority: 5,
      run: async (_args, engine) => {
        await engine.showView('doctor', '')
      },
    },
    viewCommand('runtime', 'Show raw runtime state for debugging.', 'runtime', undefined, { category: 'debug', priority: 5 }),
  ]
}

export function parseCommand(commands: Command[], text: string): CommandInvocation | null {
  const raw = text.trim()
  if (!raw.startsWith('/')) {
    return null
  }
  const body = raw.slice(1).trim()
  if (!body) {
    return null
  }

  const candidates: Array<{ command: Command; matchedName: string }> = []
  for (const command of commands) {
    const names = [command.name, ...(command.aliases || [])]
    for (const name of names) {
      const normalized = name.trim().toLowerCase()
      const loweredBody = body.toLowerCase()
      if (loweredBody === normalized || loweredBody.startsWith(`${normalized} `)) {
        candidates.push({ command, matchedName: name })
      }
    }
  }

  if (candidates.length === 0) {
    return null
  }
  candidates.sort((left, right) => right.matchedName.length - left.matchedName.length)
  const selected = candidates[0]
  const args = body.slice(selected.matchedName.length).trim()
  return {
    command: selected.command,
    args,
    matchedName: selected.matchedName,
  }
}

function commandRoot(command: Command): string {
  return command.name.trim().split(/\s+/)[0] || command.name
}

function isNestedCommand(command: Command): boolean {
  return command.name.trim().includes(' ')
}

function startsCommandText(command: Command, raw: string): boolean {
  const names = [command.name, ...(command.aliases || [])]
  const primary = [...names, ...(command.keywords || [])].map(item => item.toLowerCase())
  if (primary.some(item => item.startsWith(raw) || item.split(/\s+/).some(part => part.startsWith(raw)))) {
    return true
  }
  if (raw.length < 2) {
    return false
  }
  return [
    command.description,
    command.category || '',
  ].map(item => item.toLowerCase()).some(item => item.includes(raw))
}

export function matchCommands(commands: Command[], text: string, recent: string[], state?: AppState): Command[] {
  const withoutSlash = text.replace(/^\s*\//, '')
  const raw = withoutSlash.trim().toLowerCase()
  const rootToken = raw.split(/\s+/)[0] || ''
  const hasTrailingSpace = /\S\s+$/.test(withoutSlash)
  const rootExists = commands.some(command => command.name === rootToken && !isNestedCommand(command))
  const secondLevelMode = Boolean(rootToken && rootExists && (hasTrailingSpace || raw.includes(' ')))
  const filtered = (() => {
    if (secondLevelMode) {
      const prefix = `${rootToken} `
      return commands.filter(command => command.name.startsWith(prefix) && command.name.toLowerCase().startsWith(raw))
    }
    const topLevel = commands.filter(command => !isNestedCommand(command))
    if (!raw) {
      return topLevel
    }
    return topLevel.filter(command => startsCommandText(command, raw))
  })()

  return [...filtered].sort((left, right) => {
    const pendingActive = Boolean(state?.permissions.pending?.active)
    if (pendingActive && left.category !== right.category) {
      if (left.category === 'approval') {
        return -1
      }
      if (right.category === 'approval') {
        return 1
      }
    }
    const activeTasks = Object.values(state?.tasks.items || {}).some(task => ['started', 'running'].includes(task.status))
    if (activeTasks && left.category !== right.category) {
      if (left.category === 'runtime') {
        return -1
      }
      if (right.category === 'runtime') {
        return 1
      }
    }
    const leftRecent = recent.indexOf(left.name)
    const rightRecent = recent.indexOf(right.name)
    if (leftRecent >= 0 && rightRecent >= 0) {
      return leftRecent - rightRecent
    }
    if (leftRecent >= 0) {
      return -1
    }
    if (rightRecent >= 0) {
      return 1
    }
    const priority = (right.priority || 0) - (left.priority || 0)
    if (priority !== 0) {
      return priority
    }
    const leftRoot = commandRoot(left)
    const rightRoot = commandRoot(right)
    if (leftRoot !== rightRoot) {
      return leftRoot.localeCompare(rightRoot)
    }
    return left.name.localeCompare(right.name)
  })
}

export function hasNestedCommands(commands: Command[], commandName: string): boolean {
  const normalized = commandName.trim().toLowerCase()
  if (!normalized || normalized.includes(' ')) {
    return false
  }
  return commands.some(command => command.name.toLowerCase().startsWith(`${normalized} `))
}

export function resolvePaletteSelection(
  commands: Command[],
  input: string,
  selectedCommand: Command | undefined,
): { action: 'insert' | 'submit'; text: string } | null {
  if (!selectedCommand) {
    return null
  }
  const commandBody = input.trim().replace(/^\//, '')
  const selectedName = selectedCommand.name
  const selectedNameLower = selectedName.toLowerCase()
  const commandPrefix = commandBody.toLowerCase()

  if (hasNestedCommands(commands, selectedName)) {
    return {
      action: 'insert',
      text: `/${selectedName} `,
    }
  }

  if (selectedCommand.argumentHint?.startsWith('<') && selectedNameLower === commandPrefix) {
    return {
      action: 'insert',
      text: `/${selectedName} `,
    }
  }

  if (selectedName !== commandBody && selectedNameLower.startsWith(commandPrefix)) {
    if (selectedCommand.argumentHint?.startsWith('<')) {
      return {
        action: 'insert',
        text: `/${selectedName} `,
      }
    }
    return {
      action: 'submit',
      text: `/${selectedName}`,
    }
  }

  return {
    action: 'submit',
    text: input,
  }
}

export async function runCommand(invocation: CommandInvocation, engine: QueryEngine): Promise<void | 'quit'> {
  if (invocation.command.type === 'prompt') {
    const prompt = await (invocation.command as PromptCommand).getPrompt(invocation.args, engine)
    await engine.submitPrompt(prompt)
    return
  }
  const result = await (invocation.command as LocalCommand).run(invocation.args, engine)
  if (result === 'quit') {
    return engine.quit()
  }
  return undefined
}
