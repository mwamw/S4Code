import { describe, expect, test } from 'bun:test'
import { getCommands, matchCommands, parseCommand } from '../src/commands'
import { getDefaultAppState } from '../src/state/AppStateStore'

describe('commands', () => {
  test('parseCommand chooses the longest matching command name', () => {
    const invocation = parseCommand(getCommands(), '/task output build-1')

    expect(invocation?.command.name).toBe('task output')
    expect(invocation?.args).toBe('build-1')
  })

  test('matchCommands prioritizes approval commands when pending', () => {
    const state = getDefaultAppState()
    state.permissions.pending = {
      active: true,
      title: 'Approval required',
    }

    const matches = matchCommands(getCommands(), '/', [], state)

    expect(matches.slice(0, 3).map(command => command.name)).toContain('confirm')
    expect(matches.slice(0, 3).map(command => command.name)).toContain('deny')
  })

  test('registry includes high-frequency parity commands', () => {
    const names = new Set(getCommands().map(command => command.name))

    for (const name of [
      'status',
      'context',
      'cost',
      'trace',
      'help',
      'tools',
      'skills',
      'mcp',
      'worktree',
      'session list',
      'session checkpoints',
      'tasks',
      'task output',
      'pending',
      'confirm',
      'deny',
      'answer',
      'model',
      'permissions',
      'compact',
      'diff',
      'review',
      'doctor',
      'quit',
    ]) {
      expect(names.has(name)).toBe(true)
    }
  })
})
