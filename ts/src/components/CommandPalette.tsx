import React from 'react'
import { Box, Text } from 'ink'
import type { Command } from '../types/command'

export function CommandPalette(props: { commands: Command[]; visible: boolean; selectedIndex: number }) {
  if (!props.visible || props.commands.length === 0) {
    return null
  }
  const visibleCommands = props.commands.slice(0, 12)
  const selectedIndex = Math.min(Math.max(props.selectedIndex, 0), visibleCommands.length - 1)
  return (
    <Box flexDirection="column" borderStyle="round" borderColor="gray" paddingX={1} marginTop={1}>
      <Text color="cyan">Commands</Text>
      {visibleCommands.map((command, index) => (
        <Text
          key={command.name}
          color={index === selectedIndex ? 'black' : undefined}
          backgroundColor={index === selectedIndex ? 'cyan' : undefined}
        >
          {index === selectedIndex ? '> ' : '  '}
          /{command.name}{command.argumentHint ? ` ${command.argumentHint}` : ''} — {command.description}
        </Text>
      ))}
      {props.commands.length > visibleCommands.length ? (
        <Text color="gray">  +{props.commands.length - visibleCommands.length} more</Text>
      ) : null}
    </Box>
  )
}
