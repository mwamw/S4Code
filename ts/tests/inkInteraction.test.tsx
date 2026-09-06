import { afterEach, expect, test } from 'bun:test'
import React from 'react'
import { render } from 'ink'
import { PassThrough } from 'node:stream'
import { App } from '../src/components/App'
import { REPL } from '../src/screens/REPL'
import { getDefaultAppState } from '../src/state/AppStateStore'
import { createStore } from '../src/state/store'
import { InkController } from '../src/controller/InkController'
import { InkCoreClient } from '../src/controller/InkCoreClient'
import { BridgeClient, type BridgeTransport, type BridgeEnvelope, type BridgeRequest } from '../packages/bridge-client/src/index'

const cleanup: Array<() => void> = []
afterEach(() => { for (const dispose of cleanup.splice(0)) dispose() })
const pause = (ms = 60) => new Promise(resolve => setTimeout(resolve, ms))
async function until(check: () => boolean) {
  for (let i = 0; i < 200; i++) { if (check()) return; await pause(10) }
  throw new Error('Timed out waiting for UI state')
}
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done }); return { promise, resolve } }

class CoreTransport implements BridgeTransport {
  requests: BridgeRequest[] = []
  listener?: (event: BridgeEnvelope) => void
  handler?: (request: BridgeRequest) => unknown | Promise<unknown>
  closed = false
  state = { session_id: 's', project_root: '/tmp/test', project_name: 'test', branch: 'main', model: 'test', provider: 'test', profile: 'default', permission_mode: 'default',
    context: { estimatedRequestTokens: 120, maxTokens: 1000 }, startup_issues: [], pending: null, processes: [] as Array<{ task_id: string; status: string }> }
  subscribe(listener: (event: BridgeEnvelope) => void) { this.listener = listener; return () => { this.listener = undefined } }
  onError() { return () => {} }
  close() { this.closed = true }
  send(request: BridgeRequest) {
    this.requests.push(request)
    void Promise.resolve().then(() => this.handler ? this.handler(request) : this.result(request)).then(result => {
      this.listener?.({ request_id: request.request_id, type: 'response', ok: true, result })
    }, error => this.listener?.({ request_id: request.request_id, type: 'response', ok: false, error: { code: 'test_error', message: String(error) } }))
  }
  result(request: BridgeRequest): unknown {
    if (request.method === 'initialize') return { protocol_version: 1, session_id: 's' }
    if (request.method === 'core.state') return this.state
    if (request.method === 'core.inspect') {
      if (request.params.topic === 'models') return [{ name: 'default', model: 'large', provider: 'test', active: true }, { name: 'fast', model: 'small', provider: 'test', active: false }]
      return request.params.topic === 'restore' ? {} : []
    }
    if (request.method === 'core.session.list') return [{ session_id: 'saved-1', title: 'Saved session' }]
    if (request.method === 'core.conversation.capture') return { snapshot_id: `snap-${this.requests.length}`, created_at: 'now' }
    if (request.method === 'core.stop') return { stop_requested: false }
    if (request.method === 'core.stream') return { status: 'completed', text: 'done' }
    return {}
  }
}

function runtime() {
  const transport = new CoreTransport()
  const bridge = new BridgeClient(transport)
  const ink = new InkCoreClient(bridge)
  const store = createStore(getDefaultAppState())
  const engine = new InkController({ bridge: ink, getAppState: store.getState, setAppState: store.setState })
  cleanup.push(() => bridge.terminate())
  const input = (text: string, action: 'edit' | 'navigate' = 'edit') => {
    store.setState(prev => ({ ...prev, ui: { ...prev.ui, input: text } }))
    engine.refreshPalette(text, action)
  }
  return { transport, bridge, ink, store, engine, input }
}

async function ui() {
  const result = runtime()
  const stdout = Object.assign(new PassThrough(), { columns: 100, rows: 24, isTTY: true })
  const stdin = Object.assign(new PassThrough(), { isTTY: true, setRawMode() {}, ref() {}, unref() {} })
  const stderr = new PassThrough()
  let output = ''
  stdout.on('data', chunk => { output += chunk.toString() }); stderr.resume()
  const app = render(<App store={result.store} initialState={result.store.getState()}><REPL engine={result.engine} /></App>,
    { stdout, stdin, stderr, exitOnCtrlC: false, patchConsole: false })
  cleanup.push(() => { app.unmount(); stdout.destroy(); stdin.destroy(); stderr.destroy() })
  await pause()
  return { ...result, app, stdout, output: () => output, press: async (text: string) => { stdin.write(text); await pause() } }
}

test('model opens on Enter, loads actual profiles, and executes the selected value', async () => {
  const r = await ui()
  const choices = deferred<unknown>()
  r.transport.handler = request => request.method === 'core.inspect' && request.params.topic === 'models' ? choices.promise : r.transport.result(request)
  await r.press('/model')
  expect(r.store.getState().palette.entries[0].label).toBe('/model')
  expect(r.transport.requests).toHaveLength(0)
  await r.press('\r')
  expect(r.store.getState().ui.input).toBe('/model ')
  expect(r.store.getState().palette.loading).toBe(true)
  await r.press('\r')
  expect(r.transport.requests.some(request => request.method === 'core.model.select')).toBe(false)
  choices.resolve(r.transport.result({ method: 'core.inspect', request_id: 'models', params: { topic: 'models' } }))
  await until(() => !r.store.getState().palette.loading)
  expect(r.store.getState().palette.entries.map(entry => entry.label)).toEqual(['default (current)', 'fast'])
  await r.press('\x1b[B'); await r.press('\r')
  expect(r.transport.requests.find(request => request.method === 'core.model.select')?.params.target).toBe('fast')
})

for (const keys of [['/model', ' '], ['/mo', '\t'], ['/m', 'o', 'd', 'e', 'l']]) {
  test(`model typing and completion do not open choices before Enter: ${JSON.stringify(keys)}`, async () => {
    const r = await ui()
    for (const key of keys) await r.press(key)
    expect(r.store.getState().palette.title).toBe('Commands')
    expect(r.store.getState().palette.entries[0].label).toBe('/model')
    expect(r.store.getState().palette.loading).toBe(false)
    expect(r.transport.requests.some(request => request.method === 'core.inspect')).toBe(false)
    await r.press('\x1b[B'); await r.press('\x1b[A')
    expect(r.store.getState().palette.title).toBe('Commands')
    await r.press('\r')
    await until(() => !r.store.getState().palette.loading)
    expect(r.store.getState().palette.entries.map(entry => entry.label)).toEqual(['default (current)', 'fast'])
    expect(r.transport.requests.filter(request => request.method === 'core.inspect' && request.params.topic === 'models')).toHaveLength(1)
  })
}

test('a fully typed model command executes unchanged without fetching choices', async () => {
  const r = await ui()
  await r.press('/model custom/provider-model'); await r.press('\r')
  expect(r.transport.requests.find(request => request.method === 'core.model.select')?.params.target).toBe('custom/provider-model')
  expect(r.transport.requests.some(request => request.method === 'core.inspect' && request.params.topic === 'models')).toBe(false)
})

test('session menus are hierarchical, Esc goes back, and completion puts the cursor at the end', async () => {
  const r = await ui()
  await r.press('/session'); await r.press('\r')
  expect(r.store.getState().ui.input).toBe('/session ')
  expect(r.store.getState().palette.entries.map(entry => entry.label)).toContain('load')
  expect(r.store.getState().palette.entries.some(entry => entry.label.includes('['))).toBe(false)
  await r.press('\x1b')
  expect(r.store.getState().ui.input).toBe('/')
  await r.press('session'); await r.press('\r')
  const index = r.store.getState().palette.entries.findIndex(entry => entry.label === 'rename')
  for (let i = 0; i < index; i++) await r.press('\x1b[B')
  await r.press('\r')
  expect(r.store.getState().ui.input).toBe('/session rename ')
  await r.press('New title')
  expect(r.store.getState().ui.input).toBe('/session rename New title')
  await r.press('\r')
  expect(r.transport.requests.find(request => request.method === 'core.session.save')?.params.title).toBe('New title')
})

test('Tab and spaces do not enter session groups or load their choices', async () => {
  const r = await ui()
  await r.press('/session'); await r.press('\t'); await r.press(' ')
  expect(r.store.getState().palette.title).toBe('Commands')
  expect(r.store.getState().palette.entries[0].label).toBe('/session')
  expect(r.store.getState().palette.entries.some(entry => entry.label === 'load')).toBe(false)
  await r.press('\r')
  expect(r.store.getState().palette.title).toBe('/session')
  await r.press('load'); await r.press('\t')
  expect(r.store.getState().ui.input).toBe('/session load ')
  expect(r.store.getState().palette.entries.map(entry => entry.label)).toEqual(['load'])
  expect(r.transport.requests.some(request => request.method === 'core.session.list')).toBe(false)
  await r.press('\r')
  await until(() => !r.store.getState().palette.loading)
  expect(r.store.getState().palette.title).toBe('/session load')
  expect(r.store.getState().palette.entries[0].label).toBe('Saved session')
  await r.press('\x1b')
  expect(r.store.getState().palette.title).toBe('/session')
  expect(r.store.getState().palette.entries.map(entry => entry.label)).toContain('load')
})

test('palette ignores stale replies, reuses choices while filtering, and preserves aliases', async () => {
  const r = runtime()
  const choices = deferred<unknown>()
  r.transport.handler = request => request.method === 'core.inspect' ? choices.promise : r.transport.result(request)
  r.input('/model ', 'navigate'); r.input('/model fa'); r.input('/ctx')
  choices.resolve([{ name: 'fast', provider: 'test', model: 'small', active: false }])
  await pause(10)
  expect(r.transport.requests.filter(request => request.method === 'core.inspect')).toHaveLength(1)
  expect(r.store.getState().palette.entries[0].label).toBe('/context')
  expect(r.store.getState().palette.loading).toBe(false)
})

test('Esc cancels pending choices and retyping a command requires a new confirmation', async () => {
  const r = await ui()
  const choices = deferred<unknown>()
  r.transport.handler = request => request.method === 'core.inspect' && request.params.topic === 'models' ? choices.promise : r.transport.result(request)
  await r.press('/model'); await r.press('\r')
  expect(r.store.getState().palette.loading).toBe(true)
  await r.press('\x1b'); await r.press('model ')
  choices.resolve([{ name: 'fast', provider: 'test', model: 'small', active: false }])
  await pause(10)
  expect(r.store.getState().palette.title).toBe('Commands')
  expect(r.store.getState().palette.entries[0].label).toBe('/model')
  expect(r.store.getState().palette.loading).toBe(false)
  await r.press('\r')
  await until(() => !r.store.getState().palette.loading)
  expect(r.store.getState().palette.entries[0].label).toBe('fast')
})

test('cancel during checkpoint preparation prevents the run and holds busy until cleanup finishes', async () => {
  const r = runtime()
  const checkpoint = deferred<unknown>()
  r.transport.handler = request => request.method === 'core.conversation.capture' ? checkpoint.promise : r.transport.result(request)
  const submitted = r.engine.submitPrompt('test')
  await until(() => r.transport.requests.some(request => request.method === 'core.conversation.capture'))
  const stopped = r.engine.interrupt()
  await pause(10)
  expect(r.store.getState().runtime.busy).toBe(true)
  checkpoint.resolve({ snapshot_id: 'cp', created_at: 'now' })
  await Promise.all([submitted, stopped])
  expect(r.transport.requests.some(request => request.method === 'core.stream')).toBe(false)
  expect(r.store.getState().runtime.busy).toBe(false)
})

test('a failed interrupt keeps a still-running submission busy', async () => {
  const r = runtime()
  const response = deferred<unknown>()
  r.transport.handler = request => {
    if (request.method === 'core.stop') throw new Error('stop failed')
    return request.method === 'core.stream' ? response.promise : r.transport.result(request)
  }
  const submitted = r.engine.submitPrompt('test')
  await until(() => r.transport.requests.some(request => request.method === 'core.stream'))
  await r.engine.interrupt()
  expect(r.store.getState().runtime.busy).toBe(true)
  response.resolve({ status: 'completed', text: 'done' })
  await submitted
  expect(r.store.getState().runtime.busy).toBe(false)
})

test('cancel covers workflow prompt preparation before the Core submission exists', async () => {
  const r = runtime()
  const workflow = deferred<unknown>()
  r.transport.handler = request => request.method === 'core.workflow' ? workflow.promise : r.transport.result(request)
  const submitted = r.engine.handleInput('/review')
  await until(() => r.transport.requests.some(request => request.method === 'core.workflow'))
  await r.engine.interrupt()
  expect(r.store.getState().runtime.busy).toBe(true)
  workflow.resolve({ prompt: 'Review this change' })
  await submitted
  expect(r.transport.requests.some(request => request.method === 'core.stream')).toBe(false)
  expect(r.store.getState().runtime.busy).toBe(false)
})

test('invalid slash command produces an error card instead of an unhandled rejection', async () => {
  const r = runtime()
  await r.engine.handleInput('/no-such-command')
  expect(r.store.getState().transcript.cards.find(card => card.kind === 'error')?.body).toContain('Unknown command')
})

test('Ctrl+C shuts down the bridge and exits Ink exactly once', async () => {
  const r = await ui()
  const exited = r.app.waitUntilExit()
  await r.press('\x03')
  await exited
  await r.engine.close()
  expect(r.transport.closed).toBe(true)
  expect(r.transport.requests.filter(request => request.method === 'shutdown')).toHaveLength(1)
})

test('context fields, clear, and background task notices reach the presentation state', async () => {
  const r = runtime()
  await r.engine.showHelp()
  expect(r.store.getState().transcript.cards.some(card => card.title === 'Help')).toBe(true)
  await r.engine.handleInput('/clear')
  expect(r.store.getState().transcript.cards.some(card => card.title === 'Help')).toBe(false)
  expect(r.store.getState().context.used_tokens).toBe(120)
  expect(r.store.getState().context.usage_percent).toBe('12.0%')
  r.transport.state.processes = [{ task_id: 'background-1', status: 'running' }]
  await r.engine.pollRuntime()
  r.transport.state.processes = [{ task_id: 'background-1', status: 'completed' }]
  await r.engine.pollRuntime()
  expect(r.store.getState().transcript.cards.some(card => card.body.includes('background-1: completed'))).toBe(true)
})

test('the full conversation remains rendered when it exceeds terminal height and a menu opens', async () => {
  const r = await ui()
  const cards = Array.from({ length: 20 }, (_, index) => ({ id: `history-${index}`, kind: 'assistant' as const,
    title: `Assistant ${index}`, body: Array.from({ length: 8 }, (_, line) => `Message ${index}, line ${line}`).join('\n'), status: 'done' }))
  r.store.setState(prev => ({ ...prev, transcript: { ...prev.transcript, cards, committedCards: cards } }))
  await until(() => r.output().includes('Message 19, line 7'))
  expect(r.output()).toContain('Message 0, line 0')
  expect(r.output()).toContain('Message 10, line 0')
  expect(r.output()).not.toContain('PgUp/PgDn scroll')
  const before = r.output().length
  await r.press('/model')
  const output = r.output().slice(before)
  expect(output).toContain('Message 0, line 0')
  expect(output).toContain('Message 19, line 7')
  expect(output).toContain('Commands')
  expect(r.store.getState().palette.entries[0].label).toBe('/model')
  expect(r.transport.requests.some(request => request.method === 'core.inspect' && request.params.topic === 'models')).toBe(false)
})
