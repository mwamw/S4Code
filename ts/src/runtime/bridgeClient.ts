import { randomUUID } from 'node:crypto'
import { BridgeProcess } from './bridgeProcess'
import type {
  BridgeEnvelope,
  BridgeEventEnvelope,
  BridgeResponseEnvelope,
  ContextPayload,
  InitPayload,
  PendingPayload,
  S4BridgeEvent,
  SidebarPayload,
} from '../types/bridge'

type PendingRequest = {
  resolve: (value: unknown) => void
  reject: (error: Error) => void
  onEvent?: (event: S4BridgeEvent) => void
  timeout?: ReturnType<typeof setTimeout>
}

class BridgeClosedError extends Error {
  constructor() {
    super('Bridge process is closed')
    this.name = 'BridgeClosedError'
  }
}

export function isBridgeClosedError(error: unknown): boolean {
  return error instanceof BridgeClosedError
    || (error instanceof Error && error.message === 'Bridge process is closed')
}

export class BridgeClient {
  private process: BridgeProcess
  private pending = new Map<string, PendingRequest>()
  private closed = false

  constructor(process: BridgeProcess) {
    this.process = process
    this.process.subscribe(payload => this.handleEnvelope(payload))
    this.process.onError(error => this.failPending(error))
  }

  private failPending(error: Error): void {
    for (const [requestId, request] of this.pending.entries()) {
      if (request.timeout) {
        clearTimeout(request.timeout)
      }
      request.reject(error)
      this.pending.delete(requestId)
    }
  }

  private resolvePendingAsClosed(): void {
    for (const [requestId, request] of this.pending.entries()) {
      if (request.timeout) {
        clearTimeout(request.timeout)
      }
      request.resolve({ closed: true })
      this.pending.delete(requestId)
    }
  }

  private handleEnvelope(payload: BridgeEnvelope): void {
    const request = this.pending.get(payload.request_id)
    if (!request) {
      return
    }
    if (payload.type === 'event') {
      request.onEvent?.((payload as BridgeEventEnvelope).event)
      return
    }
    const response = payload as BridgeResponseEnvelope
    this.pending.delete(payload.request_id)
    if (request.timeout) {
      clearTimeout(request.timeout)
    }
    if (!response.ok) {
      request.reject(new Error(response.error?.message || 'Bridge request failed'))
      return
    }
    this.captureSessionId(response.result)
    request.resolve(response.result)
  }

  private captureSessionId(result: unknown): void {
    if (!result || typeof result !== 'object') {
      return
    }
    const directSessionId = 'session_id' in result ? result.session_id : undefined
    if (typeof directSessionId === 'string' && directSessionId.trim()) {
      this.process.setSessionId(directSessionId)
      return
    }
    const nestedInit = 'init' in result ? result.init : undefined
    if (nestedInit && typeof nestedInit === 'object' && 'session_id' in nestedInit) {
      const nextSessionId = nestedInit.session_id
      if (typeof nextSessionId === 'string' && nextSessionId.trim()) {
        this.process.setSessionId(nextSessionId)
      }
    }
  }

  request<T>(method: string, params: Record<string, unknown> = {}, timeoutMs = 15000): Promise<T> {
    if (this.closed) {
      return Promise.reject(new BridgeClosedError())
    }
    const requestId = randomUUID()
    return new Promise<T>((resolve, reject) => {
      const request: PendingRequest = {
        resolve: value => resolve(value as T),
        reject,
      }
      if (timeoutMs > 0) {
        request.timeout = setTimeout(() => {
          this.pending.delete(requestId)
          reject(new Error(`Bridge request timed out: ${method}`))
        }, timeoutMs)
      }
      this.pending.set(requestId, request)
      this.process.send({
        request_id: requestId,
        method,
        params,
      })
    })
  }

  stream<T>(
    method: string,
    params: Record<string, unknown>,
    onEvent: (event: S4BridgeEvent) => void,
    timeoutMs = 0,
  ): Promise<T> {
    const requestId = randomUUID()
    return new Promise<T>((resolve, reject) => {
      const request: PendingRequest = {
        resolve: value => resolve(value as T),
        reject,
        onEvent,
      }
      if (timeoutMs > 0) {
        request.timeout = setTimeout(() => {
          this.pending.delete(requestId)
          reject(new Error(`Bridge stream timed out: ${method}`))
        }, timeoutMs)
      }
      this.pending.set(requestId, request)
      this.process.send({
        request_id: requestId,
        method,
        params,
      })
    })
  }

  init(): Promise<InitPayload> {
    return this.request<InitPayload>('init')
  }

  renderView(view: string, params: Record<string, unknown> = {}): Promise<{ title: string; text: string; payload?: unknown }> {
    return this.request('render_view', { view, ...params })
  }

  buildPrompt(kind: string, params: Record<string, unknown> = {}): Promise<{ prompt: string }> {
    return this.request('build_prompt', { kind, ...params })
  }

  runAction(action: string, params: Record<string, unknown> = {}): Promise<{ text: string; init?: InitPayload }> {
    return this.request('action', { action, ...params })
  }

  submitPrompt(prompt: string, onEvent: (event: S4BridgeEvent) => void): Promise<{ done: boolean; sidebar: SidebarPayload }> {
    return this.stream('submit_prompt', { prompt }, onEvent)
  }

  resolvePending(
    action: 'approve' | 'deny' | 'answer',
    answer: string,
    onEvent: (event: S4BridgeEvent) => void,
  ): Promise<{ done: boolean; sidebar: SidebarPayload }> {
    return this.stream('resolve_pending', { action, answer }, onEvent)
  }

  getSidebar(force = false): Promise<SidebarPayload> {
    return this.request('get_sidebar_payload', { force })
  }

  getContextPanel(): Promise<ContextPayload> {
    return this.request('get_context_panel')
  }

  getPending(): Promise<PendingPayload> {
    return this.request('get_pending')
  }

  pollRuntimeNotices(): Promise<{ notices: S4BridgeEvent[]; sidebar: SidebarPayload }> {
    return this.request('poll_runtime_notices', {}, 3000)
  }

  close(): Promise<{ closed: boolean }> {
    if (this.closed) {
      return Promise.resolve({ closed: true })
    }
    return this.request<{ closed: boolean }>('shutdown')
      .finally(() => {
        this.closed = true
      })
  }

  terminate(): void {
    this.closed = true
    this.resolvePendingAsClosed()
    this.process.close()
  }
}
