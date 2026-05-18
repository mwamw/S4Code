import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { appendFileSync, existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { BridgeEnvelope, BridgeRequest } from '../types/bridge'

export class BridgeProcess {
  private readonly cwd: string
  private readonly repoRoot: string
  private readonly python: string
  private sessionId: string | null
  private listeners = new Set<(payload: BridgeEnvelope) => void>()
  private errorListeners = new Set<(error: Error) => void>()
  private closed = false
  private readonly bridgeEnv: NodeJS.ProcessEnv
  private readonly transientSession: boolean
  private ignoreSessionModelOverrides: boolean
  private child: ChildProcessWithoutNullStreams | null = null
  private stdoutBuffer = ''
  private stderrChunks: string[] = []
  private requestFile: string | null = null

  constructor(
    cwd: string,
    sessionId?: string | null,
    options: { transientSession?: boolean; ignoreSessionModelOverrides?: boolean } = {},
  ) {
    this.cwd = cwd
    this.repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')
    this.sessionId = sessionId || null
    this.transientSession = Boolean(options.transientSession)
    this.ignoreSessionModelOverrides = Boolean(options.ignoreSessionModelOverrides)
    this.python = process.env.S4CODE_PYTHON || this.findS4Python() || 'python'
    this.bridgeEnv = {
      ...process.env,
      PYTHONPATH: [this.repoRoot, process.env.PYTHONPATH].filter(Boolean).join(':'),
      S4CODE_TRANSIENT_SESSION: this.transientSession ? '1' : process.env.S4CODE_TRANSIENT_SESSION,
    }
  }

  private findS4Python(): string | null {
    const candidates = [
      join(this.repoRoot, '.venv', 'bin', 'python'),
      join(this.repoRoot, 'venv', 'bin', 'python'),
    ]
    return candidates.find(candidate => existsSync(candidate)) || null
  }

  setSessionId(sessionId: string | null | undefined): void {
    if (this.transientSession) {
      return
    }
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

  private handleStdoutLine(rawLine: string): void {
    const raw = rawLine.trim()
    if (!raw) {
      return
    }
    try {
      const payload = JSON.parse(raw) as BridgeEnvelope
      for (const listener of this.listeners) {
        listener(payload)
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      this.emitError(new Error(`Bridge returned invalid JSON: ${message}`))
    }
  }

  private flushStdout(): void {
    while (true) {
      const newlineIndex = this.stdoutBuffer.indexOf('\n')
      if (newlineIndex < 0) {
        return
      }
      const line = this.stdoutBuffer.slice(0, newlineIndex)
      this.stdoutBuffer = this.stdoutBuffer.slice(newlineIndex + 1)
      this.handleStdoutLine(line)
    }
  }

  private ensureChild(): ChildProcessWithoutNullStreams {
    if (this.child && !this.child.killed) {
      return this.child
    }
    if (this.closed) {
      throw new Error('Bridge process is closed')
    }
    const args = ['-m', 's4code.bridge', '--cwd', this.cwd]
    if (this.sessionId) {
      args.push('--session-id', this.sessionId)
    }
    if (this.transientSession) {
      args.push('--transient-session')
    }
    if (this.ignoreSessionModelOverrides) {
      args.push('--ignore-session-model-overrides')
    }
    this.requestFile = join(mkdtempSync(join(tmpdir(), 's4code-bridge-')), 'requests.ndjson')
    writeFileSync(this.requestFile, '')
    args.push('--request-file', this.requestFile)

    const child = spawn(this.python, args, {
      cwd: this.cwd,
      env: this.bridgeEnv,
      stdio: 'pipe',
    })
    child.stdout.setEncoding('utf8')
    child.stderr.setEncoding('utf8')
    this.stdoutBuffer = ''
    this.stderrChunks = []
    this.child = child

    child.stdout.on('data', chunk => {
      this.stdoutBuffer += String(chunk || '')
      this.flushStdout()
    })
    child.stderr.on('data', chunk => {
      const text = String(chunk || '')
      if (!text) {
        return
      }
      this.stderrChunks.push(text)
      if (this.stderrChunks.length > 20) {
        this.stderrChunks.shift()
      }
    })
    child.on('error', error => {
      this.child = null
      this.emitError(error)
    })
    child.on('exit', (code, signal) => {
      if (this.stdoutBuffer.trim()) {
        this.handleStdoutLine(this.stdoutBuffer)
        this.stdoutBuffer = ''
      }
      this.child = null
      if (this.closed) {
        return
      }
      if (code === 0) {
        return
      }
      const stderr = this.stderrChunks.join('').trim()
      const detail = stderr ? ` stderr: ${stderr}` : ''
      this.emitError(new Error(`Bridge process exited (code=${String(code)}, signal=${String(signal)})${detail}`))
    })
    return child
  }

  send(request: BridgeRequest): void {
    if (this.closed) {
      throw new Error('Bridge process is closed')
    }
    this.ensureChild()
    if (!this.requestFile) {
      throw new Error('Bridge request file is unavailable')
    }
    appendFileSync(this.requestFile, `${JSON.stringify(request)}\n`)
    if (request.method === 'init') {
      this.ignoreSessionModelOverrides = false
    }
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
    if (this.child && !this.child.killed) {
      this.child.kill()
    }
    this.child = null
    if (this.requestFile) {
      try {
        rmSync(dirname(this.requestFile), { recursive: true, force: true })
      } catch {
        // Best-effort temp cleanup.
      }
      this.requestFile = null
    }
  }
}
