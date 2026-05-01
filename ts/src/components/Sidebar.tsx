import React from 'react'
import { Box, Text } from 'ink'
import type { SidebarPayload } from '../types/bridge'

function line(label: string, value: string): string {
  return `${label}: ${value}`
}

export function Sidebar(props: { payload: SidebarPayload }) {
  const payload = props.payload || {}
  const context = payload.context || {}
  const skills = payload.skills || {}
  const deferred = payload.deferred_tools || {}
  const mcp = payload.mcp || {}
  const pending = payload.pending || {}
  return (
    <Box flexDirection="column" width={36} borderStyle="round" borderColor="blue" paddingX={1}>
      <Text bold>{String(payload.project_name || 'S4Code')}</Text>
      <Text>{line('Branch', String(payload.branch || '-'))}</Text>
      <Text>{line('Model', `${String(payload.model || '-')} via ${String(payload.provider || '-')}`)}</Text>
      <Text>{line('Session', String(payload.session_id || '-'))}</Text>
      <Text>{line('Permissions', String(payload.permission_mode || '-'))}</Text>
      <Text>{line('Context', `${String(context.usage_bar || '[----------------]')} ${String(context.usage_percent || '-')}`)}</Text>
      <Text>{line('Skills', `${(skills.active || []).length} active / ${(skills.queued || []).length} queued`)}</Text>
      <Text>{line('Deferred', `${deferred.loaded || 0} loaded / ${deferred.pending_schema || 0} waiting`)}</Text>
      <Text>{line('Tasks', `${payload.active_background_count || 0} active / ${payload.failed_background_count || 0} failed`)}</Text>
      {mcp.enabled ? (
        <Text>{line('MCP', `${mcp.connected || 0} connected / ${mcp.unavailable || 0} unavailable`)}</Text>
      ) : (
        <Text>{line('MCP', 'disabled')}</Text>
      )}
      {pending.active ? (
        <Text>{line('Pending', `${String(pending.title || 'Approval required')} (${String(pending.risk_level || 'unknown')})`)}</Text>
      ) : (
        <Text>{line('Pending', 'none')}</Text>
      )}
      {payload.restore && typeof payload.restore.summary === 'string' ? (
        <Text>{line('Continuity', String(payload.restore.summary || ''))}</Text>
      ) : null}
    </Box>
  )
}
