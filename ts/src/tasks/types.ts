export type TaskLifecycle = 'started' | 'running' | 'completed' | 'failed' | 'stopped'

export type RuntimeTask = {
  id: string
  title: string
  status: TaskLifecycle
  kind: 'background' | 'subagent'
}
