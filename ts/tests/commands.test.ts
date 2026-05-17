import { describe, expect, test } from 'bun:test'
import { getCommands, matchCommands, parseCommand, resolvePaletteSelection } from '../src/commands'
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
      'checkpoint',
      'checkpoints',
      'rewind',
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

  test('matchCommands shows top-level command groups before nested commands', () => {
    const state = getDefaultAppState()
    const rootMatches = matchCommands(getCommands(), '/', [], state).map(command => command.name)

    expect(rootMatches).toContain('session')
    expect(rootMatches).toContain('skills')
    expect(rootMatches).toContain('mcp')
    expect(rootMatches).not.toContain('session list')
    expect(rootMatches).not.toContain('skills queue')
    expect(rootMatches).not.toContain('mcp tools')
  })

  test('matchCommands shows nested choices after selecting a command group', () => {
    const state = getDefaultAppState()

    expect(matchCommands(getCommands(), '/session', [], state).map(command => command.name)).toEqual(
      expect.arrayContaining(['session list', 'session load', 'session checkpoints']),
    )
    expect(matchCommands(getCommands(), '/session ', [], state).map(command => command.name)).toEqual(
      expect.arrayContaining(['session list', 'session load', 'session checkpoints']),
    )
    expect(matchCommands(getCommands(), '/mcp', [], state).map(command => command.name)).toEqual(
      expect.arrayContaining(['mcp server', 'mcp tools', 'mcp resources', 'mcp refresh']),
    )
    expect(matchCommands(getCommands(), '/skills ', [], state).map(command => command.name)).toEqual(
      expect.arrayContaining(['skills queue', 'skills clear']),
    )
    expect(matchCommands(getCommands(), '/mcp ', [], state).map(command => command.name)).toEqual(
      expect.arrayContaining(['mcp server', 'mcp tools', 'mcp resources', 'mcp refresh']),
    )
    expect(matchCommands(getCommands(), '/session l', [], state).map(command => command.name)).toContain('session list')
  })

  test('resolvePaletteSelection expands command groups before execution', () => {
    const commands = getCommands()
    const session = commands.find(command => command.name === 'session')
    const sessionLoad = commands.find(command => command.name === 'session load')
    const sessionList = commands.find(command => command.name === 'session list')

    expect(resolvePaletteSelection(commands, '/se', session)).toEqual({
      action: 'insert',
      text: '/session ',
    })
    expect(resolvePaletteSelection(commands, '/session load', sessionLoad)).toEqual({
      action: 'insert',
      text: '/session load ',
    })
    expect(resolvePaletteSelection(commands, '/session l', sessionList)).toEqual({
      action: 'submit',
      text: '/session list',
    })
  })
})
