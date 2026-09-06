import { expect, test } from 'bun:test'
import { Checkpoints } from '../src/controller/Checkpoints'

test('checkpoint traffic contains only references, stays bounded, and serializes concurrent writes', async () => {
  const requests: Array<{ method: string; params: Record<string, unknown> }> = []
  let sequence = 0
  const checkpoints = new Checkpoints(async <T>(method: string, params: Record<string, unknown> = {}) => {
    requests.push({ method, params })
    return (method === 'core.conversation.capture' ? { snapshot_id: `snapshot-${++sequence}`, created_at: 'now' } : { persisted: true }) as T
  })
  await Promise.all(Array.from({ length: 35 }, (_, index) => checkpoints.create(`Checkpoint ${index}`)))
  expect(checkpoints.list()).toHaveLength(30)
  expect(new Set(checkpoints.list().map(item => item.snapshot_id)).size).toBe(30)
  const writes = requests.filter(request => request.method === 'core.extension.write')
  expect(writes).toHaveLength(35)
  expect(Math.max(...writes.map(request => JSON.stringify(request).length))).toBeLessThan(10000)
  expect(requests.some(request => request.method === 'core.conversation.export')).toBe(false)
  expect(requests.filter(request => request.method === 'core.conversation.delete_snapshots')).toHaveLength(5)
  await checkpoints.rewind('last')
  expect(requests.at(-1)).toEqual({ method: 'core.conversation.restore_ref', params: { snapshot_id: 'snapshot-35' } })
})

test('legacy inline snapshots are imported server-side without reading their bodies', async () => {
  const requests: Array<{ method: string; params: Record<string, unknown> }> = []
  const checkpoints = new Checkpoints(async <T>(method: string, params: Record<string, unknown> = {}) => {
    requests.push({ method, params })
    if (method === 'core.extension.read') return { checkpoints: [{ checkpoint_id: 'legacy', label: 'Legacy', created_at: 'then', snapshot: null }] } as T
    return (method === 'core.conversation.capture' ? { snapshot_id: 'reference', created_at: 'now' } : {}) as T
  })
  await checkpoints.load('session')
  expect(requests[0].params.exclude_fields).toEqual(['snapshot', 'state', 'history'])
  expect(requests[1]).toEqual({ method: 'core.conversation.capture', params: { source: { namespace: 'ink', path: ['checkpoints', 0, 'snapshot'], format: 'snapshot' } } })
  expect(checkpoints.list()[0]).toEqual({ checkpoint_id: 'legacy', label: 'Legacy', created_at: 'then', snapshot_id: 'reference' })
})

test('uncertain manifest writes never delete snapshots which may already have been persisted', async () => {
  let fail = false
  let sequence = 0
  const deleted: unknown[] = []
  const checkpoints = new Checkpoints(async <T>(method: string, params: Record<string, unknown> = {}) => {
    if (method === 'core.extension.write' && fail) throw new Error('disk full')
    if (method === 'core.conversation.delete_snapshots') deleted.push(params.snapshot_ids)
    return (method === 'core.conversation.capture' ? { snapshot_id: `snapshot-${++sequence}`, created_at: 'now' } : {}) as T
  })
  await checkpoints.create('saved')
  fail = true
  await expect(checkpoints.create('failed')).rejects.toThrow('disk full')
  expect(checkpoints.list().map(item => item.label)).toEqual(['saved'])
  expect(deleted).toEqual([])
})

test('failed or disabled autosave preserves snapshots referenced by the last durable manifest', async () => {
  let deletes = 0
  const checkpoints = new Checkpoints(async <T>(method: string) => {
    if (method === 'core.conversation.delete_snapshots') deletes++
    return (method === 'core.conversation.capture' ? { snapshot_id: crypto.randomUUID(), created_at: 'now' } : { saved: true, persisted: false }) as T
  })
  for (let i = 0; i < 31; i++) await checkpoints.create()
  expect(checkpoints.list()).toHaveLength(30)
  expect(deletes).toBe(0)
})
