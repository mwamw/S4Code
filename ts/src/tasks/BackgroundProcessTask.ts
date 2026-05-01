import type { RuntimeTask } from './types'

export function createBackgroundProcessTask(id: string, title: string, status: RuntimeTask['status']): RuntimeTask {
  return {
    id,
    title,
    status,
    kind: 'background',
  }
}
