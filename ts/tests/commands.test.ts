import { describe, expect, test } from 'bun:test'
import { getCommands, matchCommands, parseCommand, resolvePaletteSelection } from '../src/commands'
import { getDefaultAppState } from '../src/state/AppStateStore'
import { CommandMenu } from '../src/commands/CommandMenu'

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

  test('command name prefixes outrank matches in descriptions', () => {
    expect(matchCommands(getCommands(), '/mo', ['plan'])[0]?.name).toBe('model')
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

    expect(matchCommands(getCommands(), '/session', [], state)[0]?.name).toBe('session')
    expect(matchCommands(getCommands(), '/session ', [], state).map(command => command.name)).toEqual(
      expect.arrayContaining(['session list', 'session load', 'session checkpoints']),
    )
    expect(matchCommands(getCommands(), '/mcp', [], state)[0]?.name).toBe('mcp')
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

  test('menu navigation is explicit and editing a confirmed prefix returns to its parent', () => {
    const menu = new CommandMenu(getCommands())
    const state = getDefaultAppState()
    expect(menu.describe('/model ', state).source).toBeUndefined()
    menu.open('/model ')
    expect(menu.describe('/model ', state).source).toBe('models')
    expect(menu.describe('/model fa', state).query).toBe('fa')
    expect(menu.describe('/model', state).source).toBeUndefined()
    expect(menu.describe('/model ', state).source).toBeUndefined()
    menu.open('/session load ')
    expect(menu.describe('/session load ', state).source).toBe('sessions')
    expect(menu.describe('/session load', state).title).toBe('/session')
    expect(menu.describe('/session load ', state).source).toBeUndefined()
    menu.open('')
    expect(menu.describe('/session ', state).title).toBe('Commands')
  })

  test('argument syntax stays in help, not in menu labels, descriptions or hints', () => {
    const menu = new CommandMenu(getCommands())
    const state = getDefaultAppState()
    for (const input of ['/', '/session ', '/session rename ', '/model ', '/permissions ']) {
      menu.open(input)
      const page = menu.describe(input, state)
      const visibleText = [page.title, page.hint, ...page.entries.map(entry => `${entry.label} ${entry.description}`)].join('\n')
      expect(visibleText).not.toMatch(/[<>\[\]|]/)
    }
  })
})
