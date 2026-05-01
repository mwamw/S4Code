import React from 'react'
import { Text } from 'ink'
import { useAppState } from '../state/AppState'

export function FooterPane() {
  const recentCommands = useAppState(state => state.palette.recentCommands)
  if (recentCommands.length === 0) {
    return null
  }
  return <Text color="gray">Recent: {recentCommands.slice(0, 5).map(name => `/${name}`).join(', ')}</Text>
}
