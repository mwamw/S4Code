import type { RuntimeTask } from './types'

export function createSubagentTask(id: string, title: string, status: RuntimeTask['status']): RuntimeTask {
  return {
    id,
    title,
    status,
    kind: 'subagent',
  }
}
