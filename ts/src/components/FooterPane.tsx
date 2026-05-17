import React from 'react'
import { Box, Text, useStdout } from 'ink'
import { useAppState } from '../state/AppState'

function truncateMiddle(value: string, maxLength: number): string {
  const text = String(value || '')
  if (text.length <= maxLength) {
    return text
  }
  if (maxLength <= 3) {
    return text.slice(0, maxLength)
  }
  const left = Math.ceil((maxLength - 1) / 2)
  const right = Math.floor((maxLength - 1) / 2)
  return `${text.slice(0, left)}…${text.slice(-right)}`
}

export function FooterPane() {
  const { stdout } = useStdout()
  const recentCommands = useAppState(state => state.palette.recentCommands)
  const branch = useAppState(state => state.project.branch)
  const modelLabel = useAppState(state => {
    const profile = state.model.profile && state.model.profile !== 'default' ? `${state.model.profile}:` : ''
    const provider = state.model.provider && state.model.provider !== '-' ? `${state.model.provider}/` : ''
    return `${profile}${provider}${state.model.model || '-'}`
  })
  const contextLabel = useAppState(state => {
    const used = typeof state.context.used_tokens === 'number' ? state.context.used_tokens.toLocaleString() : '-'
    const max = typeof state.context.max_tokens === 'number' ? state.context.max_tokens.toLocaleString() : '-'
    const usage = state.context.usage_percent || '-'
    return `${usage} (${used}/${max})`
  })
  const width = stdout?.columns || 100
  const recentLabel = recentCommands.length > 0
    ? `Recent: ${recentCommands.slice(0, 3).map(name => `/${name}`).join(', ')}`
    : ''
  const fixedWidth = branch.length + contextLabel.length + recentLabel.length + 16
  const modelWidth = Math.max(18, Math.min(48, width - fixedWidth))
  const visibleModel = truncateMiddle(modelLabel, modelWidth)

  return (
    <Box flexDirection="row" justifyContent="space-between" width="100%">
      <Box flexShrink={1}>
        <Text wrap="truncate-end">
          <Text color="cyan">{branch}</Text>
          <Text color="gray"> · </Text>
          <Text color="yellow">{visibleModel}</Text>
          <Text color="gray"> · ctx: </Text>
          <Text color="green">{contextLabel}</Text>
        </Text>
      </Box>
      {recentLabel ? (
        <Text color="gray" wrap="truncate-end">{recentLabel}</Text>
      ) : null}
    </Box>
  )
}
