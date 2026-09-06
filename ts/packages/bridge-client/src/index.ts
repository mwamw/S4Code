import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { randomUUID } from 'node:crypto'

export type RunEvent = { type: string; run_id: string; session_id: string; sequence: number; content: string; data: Record<string, unknown> }
export type RunResult = { run_id: string; session_id: string; status: 'completed' | 'interaction_required' | 'cancelled' | 'failed'; text: string; interaction?: InteractionRequest | null; error?: string | null }
export type InteractionRequest = { interaction_id: string; session_id: string; kind: string; tool_name: string; arguments: Record<string, unknown>; details: Record<string, unknown> }
export type SessionInfo = { session_id: string; title: string; project_root: string; model: string; provider: string; forked_from_session_id?: string | null }
export type Snapshot = { version: 1; session_id: string; state: Record<string, unknown> }
export type BridgeRequest = { request_id: string; method: string; params: Record<string, unknown> }
export type BridgeEnvelope = { request_id: string; type: 'response'; ok: boolean; result?: unknown; error?: { code: string; message: string } } | { request_id: string; type: 'event'; event: RunEvent }
export interface BridgeTransport {
  send(request: BridgeRequest): void
  subscribe(listener: (value: BridgeEnvelope) => void): () => void
  onError(listener: (error: Error) => void): () => void
  close(): void
}
export type BridgeOptions = { cwd?: string; python?: string; sessionId?: string | null; transientSession?: boolean }

type NativeBunProcess = {
  stdin: { write(value: string): number; flush(): number | Promise<number>; end(): void }
  stdout: ReadableStream<Uint8Array>
  stderr: ReadableStream<Uint8Array>
  exited: Promise<number>
  kill(): void
}
type BunProcessAPI = { spawn(args: string[], options: { cwd?: string; stdin: 'pipe'; stdout: 'pipe'; stderr: 'pipe' }): NativeBunProcess }
const bunProcessAPI = (globalThis as typeof globalThis & { Bun?: BunProcessAPI }).Bun

export class BridgeError extends Error {
  constructor(readonly code: string, message: string) { super(message); this.name = 'BridgeError' }
}

export class BridgeProcess implements BridgeTransport {
  private child: ChildProcessWithoutNullStreams | null = null
  private nativeChild: NativeBunProcess | null = null
  private closed = false
  private listeners = new Set<(event: BridgeEnvelope) => void>()
  private errors = new Set<(error: Error) => void>()
  private buffer = ''
  constructor(private options: BridgeOptions = {}) {}
  private fail(error: Error): void { for (const listener of this.errors) listener(error) }
  private acceptChunk(chunk: string): void {
    this.buffer += chunk
    let newline: number
    while ((newline = this.buffer.indexOf('\n')) >= 0) {
      const line = this.buffer.slice(0, newline); this.buffer = this.buffer.slice(newline + 1)
      if (!line.trim()) continue
      if (line.length > 16 * 1024 * 1024) { this.fail(new BridgeError('protocol_error', 'Bridge frame exceeds size limit')); this.close(); return }
      try {
        const value = JSON.parse(line) as BridgeEnvelope
        if (!value || typeof value.request_id !== 'string' || !['event', 'response'].includes(value.type)) throw new Error('Invalid envelope')
        for (const listener of this.listeners) listener(value)
      } catch { this.fail(new BridgeError('protocol_error', 'Invalid bridge response')); this.close(); return }
    }
    if (this.buffer.length > 16 * 1024 * 1024) { this.fail(new BridgeError('protocol_error', 'Bridge frame exceeds size limit')); this.close() }
  }
  private arguments(): string[] {
    const args = ['-u', '-m', 's4code.interfaces.bridge.server', '--cwd', this.options.cwd || process.cwd()]
    if (this.options.sessionId) args.push('--session-id', this.options.sessionId)
    if (this.options.transientSession) args.push('--transient-session')
    return args
  }
  private startNative(): NativeBunProcess {
    if (this.closed) throw new BridgeError('closed', 'Bridge process is closed')
    if (this.nativeChild) return this.nativeChild
    const child = bunProcessAPI!.spawn([this.options.python || process.env.S4CODE_PYTHON || 'python', ...this.arguments()],
      { cwd: this.options.cwd, stdin: 'pipe', stdout: 'pipe', stderr: 'pipe' })
    this.nativeChild = child
    const consume = async (stream: ReadableStream<Uint8Array>, output: boolean): Promise<void> => {
      const reader = stream.getReader(), decoder = new TextDecoder()
      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          if (output) this.acceptChunk(decoder.decode(value, { stream: true }))
        }
        if (output) this.acceptChunk(decoder.decode())
      } finally { reader.releaseLock() }
    }
    const drains = Promise.all([consume(child.stdout, true), consume(child.stderr, false)]).catch(error => { this.fail(error); this.close() })
    void child.exited.then(async () => {
      await drains
      if (!this.closed) this.fail(new BridgeError('disconnected', 'Bridge process exited'))
      this.closed = true; this.nativeChild = null
    }).catch(error => { this.fail(error); this.close() })
    return child
  }
  private start(): ChildProcessWithoutNullStreams {
    if (this.closed) throw new BridgeError('closed', 'Bridge process is closed')
    if (this.child) return this.child
    const args = this.arguments()
    const child = spawn(this.options.python || process.env.S4CODE_PYTHON || 'python', args, { cwd: this.options.cwd, stdio: 'pipe' })
    this.child = child
    child.stdout.setEncoding('utf8')
    child.stdout.on('data', (chunk: string) => this.acceptChunk(chunk))
    // Drain diagnostics without leaking provider configuration into protocol errors.
    child.stderr.resume()
    child.stdin.on('error', error => this.fail(error))
    child.on('error', error => { this.fail(error); this.close() })
    child.on('close', () => {
      if (!this.closed) this.fail(new BridgeError('disconnected', 'Bridge process exited'))
      this.closed = true
      this.child = null
    })
    return child
  }
  send(request: BridgeRequest): void {
    if (bunProcessAPI) {
      const child = this.startNative()
      child.stdin.write(JSON.stringify(request) + '\n')
      void Promise.resolve(child.stdin.flush()).catch(error => this.fail(error))
      return
    }
    const child = this.start()
    if (child.stdin.writableLength > 1024 * 1024) throw new BridgeError('backpressure', 'Bridge input buffer is full')
    child.stdin.write(JSON.stringify(request) + '\n')
  }
  subscribe(listener: (event: BridgeEnvelope) => void): () => void { this.listeners.add(listener); return () => this.listeners.delete(listener) }
  onError(listener: (error: Error) => void): () => void { this.errors.add(listener); return () => this.errors.delete(listener) }
  close(): void {
    this.closed = true
    this.child?.stdin.end(); this.child?.kill(); this.child = null
    this.nativeChild?.stdin.end(); this.nativeChild?.kill(); this.nativeChild = null
  }
}

type Pending = { resolve: (value: unknown) => void; reject: (error: Error) => void; onEvent?: (event: RunEvent) => void; timer?: ReturnType<typeof setTimeout> }

export class BridgeClient {
  private pending = new Map<string, Pending>()
  private closed = false
  private unsubscribe: Array<() => void>
  constructor(private transport: BridgeTransport = new BridgeProcess()) {
    this.unsubscribe = [transport.subscribe(value => this.receive(value)), transport.onError(error => this.fail(error))]
  }
  private fail(error: Error): void {
    for (const pending of this.pending.values()) { clearTimeout(pending.timer); pending.reject(error) }
    this.pending.clear()
  }
  private receive(value: BridgeEnvelope): void {
    const pending = this.pending.get(value.request_id)
    if (!pending) return
    if (value.type === 'event') {
      try { pending.onEvent?.(value.event) } catch (error) {
        clearTimeout(pending.timer); this.pending.delete(value.request_id)
        pending.reject(error instanceof Error ? error : new Error(String(error)))
        void this.request('core.stop', { session_id: value.event.session_id, run_id: value.event.run_id }).catch(() => undefined)
      }
      return
    }
    clearTimeout(pending.timer); this.pending.delete(value.request_id)
    if (value.ok) pending.resolve(value.result)
    else pending.reject(new BridgeError(value.error?.code || 'operation_failed', value.error?.message || 'Bridge request failed'))
  }
  request<T>(method: string, params: Record<string, unknown> = {}, timeoutMs = 15000, onEvent?: (event: RunEvent) => void): Promise<T> {
    if (this.closed) return Promise.reject(new BridgeError('closed', 'Bridge client is closed'))
    if (this.pending.size >= 128) return Promise.reject(new BridgeError('backpressure', 'Too many outstanding requests'))
    const id = randomUUID()
    return new Promise<T>((resolve, reject) => {
      const pending: Pending = { resolve: value => resolve(value as T), reject, onEvent }
      if (timeoutMs > 0) pending.timer = setTimeout(() => {
        this.pending.delete(id); reject(new BridgeError('timeout', `Request timed out: ${method}; outcome may be unknown`))
      }, timeoutMs)
      this.pending.set(id, pending)
      try { this.transport.send({ request_id: id, method, params }) }
      catch (error) { clearTimeout(pending.timer); this.pending.delete(id); reject(error) }
    })
  }
  stream(params: Record<string, unknown>, onEvent: (event: RunEvent) => void): Promise<RunResult> {
    return this.request('core.stream', params, 0, onEvent)
  }
  async initialize(): Promise<{ session_id: string; protocol_version: number }> {
    const result = await this.request<{ session_id: string; protocol_version: number }>('initialize', { protocol_version: 1 })
    if (result.protocol_version !== 1) throw new BridgeError('protocol_version', 'Unsupported bridge protocol')
    return result
  }
  async close(): Promise<void> {
    if (this.closed) return
    try { await this.request('shutdown', {}, 5000) } finally { this.terminate() }
  }
  terminate(): void {
    if (this.closed) return
    this.closed = true; this.fail(new BridgeError('closed', 'Bridge client is closed'))
    for (const dispose of this.unsubscribe) dispose()
    this.transport.close()
  }
}
