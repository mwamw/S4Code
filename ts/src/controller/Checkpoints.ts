type SnapshotReference = { snapshot_id: string; created_at: string }
type Checkpoint = SnapshotReference & { checkpoint_id: string; label: string }
type LegacyCheckpoint = Partial<Checkpoint> & { checkpoint_id: string; label: string; created_at: string; snapshot?: unknown; state?: unknown; history?: unknown }
type CoreCall = <T>(method: string, params?: Record<string, unknown>) => Promise<T>

/** Ink chooses checkpoint boundaries; the large conversation never crosses the bridge. */
export class Checkpoints {
  private items: Checkpoint[] = []
  private writes: Promise<unknown> = Promise.resolve()
  constructor(private call: CoreCall) {}

  async load(_sessionId: string): Promise<void> {
    await this.writes
    let namespace = 'ink'
    let extension = await this.call<{ checkpoints?: LegacyCheckpoint[] }>('core.extension.read', {
      namespace, exclude_fields: ['snapshot', 'state', 'history'],
    })
    if (!extension.checkpoints) {
      namespace = 'terminal'
      extension = await this.call('core.extension.read', { namespace, exclude_fields: ['snapshot', 'state', 'history'] })
    }
    const previous = extension.checkpoints || []
    const items: Checkpoint[] = []
    for (const [index, item] of previous.entries()) {
      if (index < previous.length - 30) continue
      const format = 'snapshot' in item ? 'snapshot' : 'state' in item ? 'state' : 'history'
      const ref = item.snapshot_id ? { snapshot_id: item.snapshot_id } : await this.call<SnapshotReference>('core.conversation.capture', {
        source: { namespace, path: ['checkpoints', index, format], format },
      })
      items.push({ checkpoint_id: item.checkpoint_id, label: item.label, created_at: item.created_at, snapshot_id: ref.snapshot_id })
    }
    if (previous.length && (namespace !== 'ink' || previous.some(item => !item.snapshot_id))) {
      await this.call('core.extension.write', { namespace: 'ink', value: { checkpoints: items } })
    }
    this.items = items
  }

  list(): Checkpoint[] { return this.items.map(item => ({ ...item })) }

  create(label = 'Checkpoint'): Promise<string> {
    const pending = this.writes.then(async () => {
      const ref = await this.call<SnapshotReference>('core.conversation.capture')
      const item = { ...ref, checkpoint_id: `cp-${crypto.randomUUID()}`, label }
      const next = [...this.items, item].slice(-30)
      // A timeout may hide a successful write: never delete the new snapshot on an uncertain outcome.
      const saved = await this.call<{ persisted?: boolean }>('core.extension.write', { namespace: 'ink', value: { checkpoints: next } })
      const evicted = this.items.filter(old => !next.includes(old)).map(old => old.snapshot_id)
      this.items = next
      // Preserve references from the last durable manifest if autosave is disabled or failed.
      if (saved.persisted && evicted.length) await this.call('core.conversation.delete_snapshots', { snapshot_ids: evicted }).catch(() => undefined)
      return item.checkpoint_id
    })
    this.writes = pending.catch(() => undefined)
    return pending
  }

  async rewind(target = 'last'): Promise<void> {
    await this.writes
    const item = target === 'last' ? this.items.at(-1) : this.items.find(item => item.checkpoint_id === target)
      || (/^\d+$/.test(target) ? this.items[Number(target) - 1] : undefined)
    if (!item) throw new Error('Checkpoint not found')
    await this.call('core.conversation.restore_ref', { snapshot_id: item.snapshot_id })
  }
}
