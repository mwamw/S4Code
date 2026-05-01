import React from 'react'
import { Box, Text } from 'ink'
import { useAppState } from '../state/AppState'

export function FooterPane() {
  const recentCommands = useAppState(state => state.palette.recentCommands)
  const branch = useAppState(state => state.project.branch)
  const model = useAppState(state => state.model.model)
  const contextUsage = useAppState(state => state.context.usage_percent)

  return (
    <Box flexDirection="row" justifyContent="space-between" width="100%">
      <Box>
        <Text color="cyan">{branch}</Text>
        <Text color="gray"> · </Text>
        <Text color="yellow">{model}</Text>
        <Text color="gray"> · ctx: </Text>
        <Text color="green">{contextUsage}</Text>
      </Box>
      {recentCommands.length > 0 && (
        <Text color="gray">Recent: {recentCommands.slice(0, 5).map(name => `/${name}`).join(', ')}</Text>
      )}
    </Box>
  )
}
