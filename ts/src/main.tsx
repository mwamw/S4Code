import { render } from 'ink'
import React from 'react'
import { resolve } from 'node:path'
import { App } from './components/App'
import { REPL } from './screens/REPL'
import { setup } from './setup'

function parseArgs(argv: string[]) {
  let cwd = process.cwd()
  let sessionId: string | null = null
  let prompt: string | null = null
  const positionals: string[] = []

  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index]
    if ((token === '--cwd' || token === '-C') && argv[index + 1]) {
      cwd = argv[index + 1]
      index += 1
      continue
    }
    if (token === '--resume' && argv[index + 1]) {
      sessionId = argv[index + 1]
      index += 1
      continue
    }
    if ((token === '--prompt' || token === '-p') && argv[index + 1]) {
      prompt = argv[index + 1]
      index += 1
      continue
    }
    positionals.push(token)
  }

  if (!prompt && positionals.length > 0) {
    const [command, subcommand, ...rest] = positionals
    if (command === 'review') {
      prompt = `/review ${[subcommand, ...rest].filter(Boolean).join(' ')}`.trim()
    } else if (command === 'commit') {
      prompt = '/commit'
    } else if (command === 'config') {
      prompt = '/config'
    } else if (command === 'doctor') {
      prompt = '/doctor'
    } else if (command === 'session' && subcommand === 'list') {
      prompt = '/session list'
    }
  }

  return { cwd: resolve(cwd), sessionId, prompt }
}

async function buildRuntime() {
  const { cwd, sessionId, prompt } = parseArgs(process.argv.slice(2))
  return setup({ cwd, sessionId, transientSession: Boolean(prompt && !sessionId) })
}

async function runPromptMode(prompt: string): Promise<void> {
  const runtime = await buildRuntime()
  runtime.store.setState(prev => ({
    ...prev,
    runtime: {
      ...prev.runtime,
      renderMode: 'oneshot',
    },
  }))
  try {
    const result = await runtime.engine.handleInput(prompt)
    if (result === 'quit') {
      return
    }
    const cards = runtime.store.getState().transcript.cards
    for (const card of cards) {
      if (card.kind === 'assistant' || card.kind === 'system' || card.kind === 'error') {
        process.stdout.write(`${card.title}\n${card.body}\n\n`)
      }
    }
  } finally {
    await runtime.engine.close()
  }
}

async function runRepl(): Promise<void> {
  if (!process.stdin.isTTY || !process.stdout.isTTY) {
    throw new Error('Interactive REPL requires a TTY. Run S4Code in a real terminal, or use --prompt for one-shot execution.')
  }
  const runtime = await buildRuntime()
  try {
    const app = render(
      <App initialState={runtime.store.getState()} store={runtime.store}>
        <REPL engine={runtime.engine} />
      </App>,
      { exitOnCtrlC: false },
    )
    await app.waitUntilExit()
  } finally {
    await runtime.engine.close()
  }
}

async function main(): Promise<void> {
  try {
    const { prompt } = parseArgs(process.argv.slice(2))
    if (prompt) {
      await runPromptMode(prompt)
      return
    }
    await runRepl()
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    process.stderr.write(`S4Code TS failed to start: ${message}\n`)
    process.exitCode = 1
  }
}

void main()
