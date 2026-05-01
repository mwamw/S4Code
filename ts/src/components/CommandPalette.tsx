import React from 'react'
import { Box, Text } from 'ink'
import type { Command } from '../types/command'

export function CommandPalette(props: { commands: Command[]; visible: boolean }) {
  if (!props.visible || props.commands.length === 0) {
    return null
  }
  return (
    <Box flexDirection="column" borderStyle="round" borderColor="gray" paddingX={1} marginTop={1}>
      <Text color="cyan">Commands</Text>
      {props.commands.slice(0, 6).map(command => (
        <Text key={command.name}>
          /{command.name}
          {command.argumentHint ? ` ${command.argumentHint}` : ''}
          {' — '}
          {command.description}
        </Text>
      ))}
    </Box>
  )
}
