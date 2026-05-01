import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import type { BridgeEnvelope, BridgeRequest } from '../types/bridge'

type ActiveChild = {
  child: ChildProcessWithoutNullStreams
  requestId: string
  sawResponse: boolean
  stdoutBuffer: string
  stderrChunks: string[]
}

export class BridgeProcess {
  private readonly cwd: string
  private readonly python: string
  private sessionId: string | null
  private listeners = new Set<(payload: BridgeEnvelope) => void>()
  private errorListeners = new Set<(error: Error) => void>()
  private activeChildren = new Map<string, ActiveChild>()
  private closed = false
  private readonly bridgeEnv: NodeJS.ProcessEnv

  constructor(
    cwd: string,
    sessionId?: string | null,
  ) {
    this.cwd = cwd
    this.sessionId = sessionId || null
    this.python = process.env.S4CODE_PYTHON || this.findProjectPython() || 'python'
    const runtimeRoot = join(this.cwd, '.s4code', 'ts-runtime')
    this.bridgeEnv = {
      ...process.env,
      XDG_CONFIG_HOME: process.env.XDG_CONFIG_HOME || join(runtimeRoot, 'config'),
      XDG_DATA_HOME: process.env.XDG_DATA_HOME || join(runtimeRoot, 'data'),
      XDG_CACHE_HOME: process.env.XDG_CACHE_HOME || join(runtimeRoot, 'cache'),
    }
  }

  private findProjectPython(): string | null {
    const candidates = [
      join(this.cwd, '.venv', 'bin', 'python'),
      join(this.cwd, 'venv', 'bin', 'python'),
    ]
    return candidates.find(candidate => existsSync(candidate)) || null
  }

  setSessionId(sessionId: string | null | undefined): void {
    this.sessionId = sessionId || null
  }

  private emitError(error: Error): void {
    if (this.closed) {
      return
    }
    for (const listener of this.errorListeners) {
      listener(error)
    }
  }

  private handleStdoutLine(active: ActiveChild, rawLine: string): void {
    const raw = rawLine.trim()
    if (!raw) {
      return
    }
    try {
      const payload = JSON.parse(raw) as BridgeEnvelope
      if (payload.type === 'response') {
        active.sawResponse = true
      }
      for (const listener of this.listeners) {
        listener(payload)
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      this.emitError(new Error(`Bridge returned invalid JSON: ${message}`))
    }
  }

  private flushStdout(active: ActiveChild): void {
    while (true) {
      const newlineIndex = active.stdoutBuffer.indexOf('\n')
      if (newlineIndex < 0) {
        return
      }
      const line = active.stdoutBuffer.slice(0, newlineIndex)
      active.stdoutBuffer = active.stdoutBuffer.slice(newlineIndex + 1)
      this.handleStdoutLine(active, line)
    }
  }

  send(request: BridgeRequest): void {
    if (this.closed) {
      throw new Error('Bridge process is closed')
    }
    const args = ['-m', 's4code.bridge', '--cwd', this.cwd]
    if (this.sessionId) {
      args.push('--session-id', this.sessionId)
    }
    args.push('--request-json', JSON.stringify(request))

    const child = spawn(this.python, args, {
      cwd: this.cwd,
      env: this.bridgeEnv,
      stdio: 'pipe',
    })
    child.stdout.setEncoding('utf8')
    child.stderr.setEncoding('utf8')

    const active: ActiveChild = {
      child,
      requestId: request.request_id,
      sawResponse: false,
      stdoutBuffer: '',
      stderrChunks: [],
    }
    this.activeChildren.set(request.request_id, active)

    child.stdout.on('data', chunk => {
      active.stdoutBuffer += String(chunk || '')
      this.flushStdout(active)
    })
    child.stderr.on('data', chunk => {
      const text = String(chunk || '')
      if (!text) {
        return
      }
      active.stderrChunks.push(text)
      if (active.stderrChunks.length > 20) {
        active.stderrChunks.shift()
      }
    })
    child.on('error', error => {
      this.activeChildren.delete(active.requestId)
      this.emitError(error)
    })
    child.on('exit', (code, signal) => {
      this.activeChildren.delete(active.requestId)
      if (active.stdoutBuffer.trim()) {
        this.handleStdoutLine(active, active.stdoutBuffer)
        active.stdoutBuffer = ''
      }
      if (this.closed) {
        return
      }
      if (code === 0 && active.sawResponse) {
        return
      }
      const stderr = active.stderrChunks.join('').trim()
      const detail = stderr ? ` stderr: ${stderr}` : ''
      this.emitError(new Error(`Bridge request failed before a complete response (code=${String(code)}, signal=${String(signal)})${detail}`))
    })
  }

  subscribe(listener: (payload: BridgeEnvelope) => void): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  onError(listener: (error: Error) => void): () => void {
    this.errorListeners.add(listener)
    return () => this.errorListeners.delete(listener)
  }

  close(): void {
    this.closed = true
    for (const active of this.activeChildren.values()) {
      active.child.kill()
    }
    this.activeChildren.clear()
  }
}
