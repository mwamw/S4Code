import { describe, expect, test } from 'bun:test'
import { BridgeClient, type BridgeTransport } from '../src/runtime/bridgeClient'
import type { BridgeEnvelope, BridgeRequest } from '../src/types/bridge'

class FakeTransport implements BridgeTransport {
  closed = false
  listener: ((payload: BridgeEnvelope) => void) | null = null
  requests: BridgeRequest[] = []

  send(request: BridgeRequest): void {
    this.requests.push(request)
  }

  subscribe(listener: (payload: BridgeEnvelope) => void): () => void {
    this.listener = listener
    return () => {
      this.listener = null
    }
  }

  onError(_listener: (error: Error) => void): () => void {
    return () => undefined
  }

  setSessionId(_sessionId: string | null | undefined): void {}

  close(): void {
    this.closed = true
  }
}

describe('BridgeClient', () => {
  test('close resolves pending requests immediately', async () => {
    const transport = new FakeTransport()
    const client = new BridgeClient(transport)

    const pending = client.pollRuntimeNotices()
    await client.close()
    const result = await pending

    expect(result).toEqual({ closed: true })
    expect(transport.closed).toBe(true)
  })

  test('structured bridge errors become user-facing errors', async () => {
    const transport = new FakeTransport()
    const client = new BridgeClient(transport)
    const pending = client.renderView('missing')
    const request = transport.requests[0]

    transport.listener?.({
      request_id: request.request_id,
      type: 'response',
      ok: false,
      error: {
        type: 'ValueError',
        reason: 'Unknown view: missing',
        impact: 'The requested view did not render.',
        next_step: 'Run /help to see supported views.',
      },
    })

    await expect(pending).rejects.toThrow('Unknown view: missing')
    await client.close()
  })
})
