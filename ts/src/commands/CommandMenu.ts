import { hasNestedCommands, matchCommands, parseCommand, resolvePaletteSelection } from './index'
import type { AppState, PaletteEntry } from '../state/AppStateStore'
import type { Command, CommandChoice, CommandChoiceSource } from '../types/command'

export type CommandMenuPage = {
  title: string
  hint: string
  parentInput: string
  canSubmit: boolean
  entries: PaletteEntry[]
  scope: string
  source?: CommandChoiceSource
  command?: Command
  query: string
}

/** Ink owns menu navigation; Core supplies only the values for argument choices. */
export class CommandMenu {
  private path: Command[] = []

  constructor(private commands: Command[]) {}

  /** Only Enter (or explicit back navigation) confirms a menu, never typing or Tab. */
  open(input: string): void {
    const invocation = parseCommand(this.commands, input)
    this.path = invocation && !invocation.args
      ? this.commands.filter(command => command === invocation.command || invocation.command.name.startsWith(`${command.name} `))
        .sort((left, right) => left.name.length - right.name.length)
      : []
  }

  describe(input: string, state: AppState): CommandMenuPage {
    const body = input.trimStart().replace(/^\//, '')
    // Editing a confirmed prefix leaves that page; editing its query does not.
    while (this.path.length && !body.toLowerCase().startsWith(`${this.path.at(-1)!.name.toLowerCase()} `)) this.path.pop()
    const opened = this.path.at(-1)
    const invocation = parseCommand(this.commands, input)
    if (opened?.argumentHint && !hasNestedCommands(this.commands, opened.name)) {
      const command = opened
      const root = command.name.split(' ')[0]
      const query = body.slice(command.name.length).trim()
      const page: CommandMenuPage = {
        title: `/${command.name}`,
        hint: command.argumentSource || command.argumentChoices
          ? 'Choose a value, or type one and press Enter.'
          : 'Type a value and press Enter.',
        parentInput: command.name.includes(' ') ? `/${root} ` : '/',
        canSubmit: Boolean(query) || !command.argumentHint!.startsWith('<'),
        entries: [],
        scope: `arguments:${command.name}`,
        source: command.argumentSource,
        command,
        query,
      }
      return this.withChoices(page, command.argumentChoices || [])
    }

    const nested = Boolean(opened)
    const root = opened?.name || ''
    // A complete command can still be typed/pasted and executed directly. A
    // trailing space alone must not turn the root page into an argument picker.
    const matches = !nested && invocation?.args ? []
      : !nested && invocation?.command.name.includes(' ') ? [invocation.command]
      : matchCommands(
        nested ? this.commands : this.commands.filter(command => !command.name.includes(' ')),
        nested ? input : input.trimEnd(), state.palette.recentCommands, state,
      )
    return {
      title: nested ? `/${root}` : 'Commands',
      hint: '',
      parentInput: nested ? '/' : '',
      canSubmit: true,
      scope: nested ? `commands:${root}` : 'commands',
      query: body.trim(),
      entries: matches.map(command => {
        const selection = resolvePaletteSelection(this.commands, input, command)!
        return {
          label: nested ? command.name.slice(root.length + 1) : `/${command.name}`,
          description: command.description,
          insertText: selection.action === 'insert' ? selection.text : `/${command.name}`,
          executeText: selection.text,
          mode: selection.action === 'insert' ? 'insert' : 'execute',
          aliases: command.aliases,
        }
      }),
    }
  }

  withChoices(page: CommandMenuPage, choices: CommandChoice[]): CommandMenuPage {
    if (!page.command) return page
    const query = page.query.toLowerCase()
    const matching = choices.filter(choice => !query || [choice.value, choice.label || '', choice.description]
      .some(value => value.toLowerCase().includes(query)))
    matching.sort((left, right) => Number(right.value.toLowerCase() === query) - Number(left.value.toLowerCase() === query)
      || Number(Boolean(right.active)) - Number(Boolean(left.active)))
    return {
      ...page,
      entries: matching.map(choice => ({
        label: `${choice.label || choice.value}${choice.active ? ' (current)' : ''}`,
        description: choice.description,
        insertText: `/${page.command!.name} ${choice.value}`,
        executeText: `/${page.command!.name} ${choice.value}`,
        mode: 'execute',
      })),
    }
  }
}
