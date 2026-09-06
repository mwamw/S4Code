import { expect, test } from 'bun:test'
import { BridgeClient, type BridgeTransport, type BridgeEnvelope, type BridgeRequest } from '../packages/bridge-client/src/index'
import { InkCoreClient } from '../src/controller/InkCoreClient'
import { Session } from '../packages/sdk/src/index'
import { CommandMenu } from '../src/commands/CommandMenu'
import { getCommands } from '../src/commands'
import { getDefaultAppState } from '../src/state/AppStateStore'

class FakeTransport implements BridgeTransport {
  requests: BridgeRequest[] = []
  listener?: (value: BridgeEnvelope) => void
  error?: (error: Error) => void
  closed = false
  send(request: BridgeRequest): void { this.requests.push(request) }
  subscribe(listener: (value: BridgeEnvelope) => void): () => void { this.listener = listener; return () => { this.listener = undefined } }
  onError(listener: (error: Error) => void): () => void { this.error = listener; return () => { this.error = undefined } }
  close(): void { this.closed = true }
  respond(result: unknown): void {
    this.listener?.({ request_id: this.requests.at(-1)!.request_id, type: 'response', ok: true, result })
  }
}

test('bridge returns data, Ink formats model result locally', async () => {
  const transport = new FakeTransport()
  const bridge = new BridgeClient(transport)
  const ink = new InkCoreClient(bridge)
  const pending = ink.runAction('set_model', { target: 'default' })
  expect(transport.requests[0].method).toBe('core.model.select')
  transport.respond({ model: 'test', provider: 'openai' })
  expect((await pending).text).toContain('test')
  bridge.terminate()
})

test('closing rejects unfinished requests instead of reporting success', async () => {
  const transport = new FakeTransport()
  const bridge = new BridgeClient(transport)
  const pending = bridge.request('core.state').catch(error => error)
  bridge.terminate()
  expect((await pending).code).toBe('closed')
  expect(transport.closed).toBe(true)
})

test('disconnect rejects outstanding streams', async () => {
  const transport = new FakeTransport()
  const bridge = new BridgeClient(transport)
  const pending = bridge.stream({ prompt: 'hello' }, () => undefined).catch(error => error)
  transport.error?.(new Error('disconnected'))
  expect((await pending).message).toBe('disconnected')
  bridge.terminate()
})

test('events stay associated with their run and request', async () => {
  const transport = new FakeTransport()
  const bridge = new BridgeClient(transport)
  const events: string[] = []
  const pending = bridge.stream({ session_id: 's', prompt: 'hello' }, event => events.push(event.run_id))
  transport.listener?.({ request_id: transport.requests[0].request_id, type: 'event', event: {
    type: 'text_delta', run_id: 'r', session_id: 's', sequence: 1, content: 'hello', data: {},
  } })
  transport.respond({ run_id: 'r', session_id: 's', text: 'hello', status: 'completed' })
  expect((await pending).text).toBe('hello')
  expect(events).toEqual(['r'])
  bridge.terminate()
})

test('Ink command palette and UI commands do not send terminal protocol requests', async () => {
  const transport = new FakeTransport()
  const bridge = new BridgeClient(transport)
  const ink = new InkCoreClient(bridge)
  expect(new CommandMenu(getCommands()).describe('/model', getDefaultAppState()).entries[0].insertText).toBe('/model ')
  await ink.executeCommand('/sidebar show')
  await ink.executeCommand('/copy last')
  expect(transport.requests.length).toBe(0)
  bridge.terminate()
})

test('protocol version is validated', async () => {
  const transport = new FakeTransport()
  const bridge = new BridgeClient(transport)
  const pending = bridge.initialize()
  transport.respond({ protocol_version: 99, session_id: 's' })
  await expect(pending).rejects.toThrow('Unsupported bridge protocol')
  bridge.terminate()
})

test('SDK passes invalid maxIter through for validation, not as a silent default', async () => {
  const transport = new FakeTransport()
  const bridge = new BridgeClient(transport)
  const session = new Session('s', bridge)
  const result = session.run('hello', { maxIter: 0 })
  expect(transport.requests[0].params.max_iter).toBe(0)
  transport.respond({ status: 'failed', text: '' })
  await result
  bridge.terminate()
})

for (const status of ['completed', 'interaction_required', 'failed'] as const) {
  test(`Ink owns checkpoint policy and presents Core ${status} events`, async () => {
    class CoreTransport extends FakeTransport {
      override send(request: BridgeRequest): void {
        super.send(request)
        queueMicrotask(() => {
          const interaction = { interaction_id: 'i', session_id: 's', kind: 'ask_user_question',
            tool_name: 'AskUserQuestion', arguments: { question: 'Which option?' },
            details: { question: 'Which option?' } }
          let result: unknown = {}
          if (request.method === 'core.conversation.capture') result = { snapshot_id: 'snapshot', created_at: 'now' }
          if (request.method === 'core.state') result = { session_id: 's', context: {}, pending: status === 'interaction_required' ? interaction : null }
          if (request.method === 'core.stream') {
            const emit = (type: string, sequence: number, data = {}, content = '') => this.listener?.({
              request_id: request.request_id, type: 'event',
              event: { type, run_id: 'r', session_id: 's', sequence, data, content },
            })
            emit('round_start', 1, { round: 1 })
            emit(status === 'failed' ? 'error' : 'final', 2, {}, status === 'failed' ? 'failed' : 'hello')
            emit('usage', 3, { stats: { total_tokens: 12, llm_calls: 1 }, llm_invokes: [] })
            result = { status, text: status === 'completed' ? 'hello' : '', interaction: status === 'interaction_required' ? interaction : null }
            emit('run_finished', 4, result as Record<string, unknown>)
          }
          this.listener?.({ request_id: request.request_id, type: 'response', ok: true, result })
        })
      }
    }
    const transport = new CoreTransport()
    const bridge = new BridgeClient(transport)
    const ink = new InkCoreClient(bridge)
    const events: Array<Record<string, unknown>> = []
    await ink.submitPrompt('hello', event => events.push(event))
    expect(events.filter(event => event.type === 'checkpoint')).toHaveLength(2)
    expect(events.filter(event => event.type === 'final')).toHaveLength(status === 'completed' ? 1 : 0)
    expect(events.find(event => event.type === 'round_metrics')?.round).toBe(1)
    if (status === 'interaction_required') {
      const pending = events.find(event => event.type === 'interruption')?.payload as Record<string, unknown>
      expect(pending.interaction_id).toBe('i')
      expect((pending.metadata as Record<string, unknown>).interaction_type).toBe('ask_user_question')
      expect((pending.tool_args as Record<string, unknown>).question).toBe('Which option?')
    }
    expect(transport.requests.every(request => request.method.startsWith('core.'))).toBe(true)
    bridge.terminate()
  })
}
