import { BridgeClient, BridgeProcess, type BridgeOptions, type InteractionRequest, type RunEvent, type RunResult, type SessionInfo } from '../../bridge-client/src/index.js'
export { BridgeError as S4CodeError } from '../../bridge-client/src/index.js'
export type { InteractionRequest, RunEvent, RunResult, SessionInfo }

export class Session {
  constructor(readonly id: string, private client: BridgeClient) {}
  run(prompt: string, options: { maxIter?: number; onEvent?: (event: RunEvent) => void } = {}): Promise<RunResult> {
    return this.client.stream({ session_id: this.id, prompt, max_iter: options.maxIter ?? 50 }, options.onEvent || (() => undefined))
  }
  info(): Promise<SessionInfo> { return this.client.request('core.state', { session_id: this.id }) }
  save(title?: string): Promise<SessionInfo> { return this.client.request('core.session.save', { session_id: this.id, title }) }
  async fork(title?: string): Promise<Session> {
    const info = await this.client.request<SessionInfo>('core.session.fork', { session_id: this.id, title })
    await this.client.request('core.session.open', { session_id: info.session_id })
    return new Session(info.session_id, this.client)
  }
  pending(): Promise<InteractionRequest | null> { return this.client.request('core.interaction.pending', { session_id: this.id }) }
  respond(interactionId: string, action: 'approve' | 'deny' | 'answer', answer = ''): Promise<unknown> {
    return this.client.request('core.interaction.respond', { session_id: this.id, interaction_id: interactionId, action, answer })
  }
  cancel(reason = ''): Promise<{ stop_requested: boolean }> { return this.client.request('core.stop', { session_id: this.id, reason }) }
  close(): Promise<unknown> { return this.client.request('core.session.close', { session_id: this.id }) }
}

export class S4Code {
  private client: BridgeClient
  private ready: Promise<unknown> | null = null
  constructor(options: BridgeOptions = {}) { this.client = new BridgeClient(new BridgeProcess(options)) }
  private initialize(): Promise<unknown> {
    return this.ready ??= this.client.initialize().catch(error => { this.client.terminate(); throw error })
  }
  async createSession(): Promise<Session> {
    await this.initialize()
    const info = await this.client.request<SessionInfo>('core.session.create')
    return new Session(info.session_id, this.client)
  }
  async resumeSession(id: string): Promise<Session> {
    await this.initialize()
    const info = await this.client.request<SessionInfo>('core.session.open', { session_id: id })
    return new Session(info.session_id, this.client)
  }
  async listSessions(): Promise<SessionInfo[]> { await this.initialize(); return this.client.request('core.session.list') }
  async close(): Promise<void> { if (this.ready) await this.client.close(); else this.client.terminate() }
}
