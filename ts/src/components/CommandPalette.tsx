import React from 'react'
import { Box, Text } from 'ink'
import type { Command } from '../types/command'

export function CommandPalette(props: { commands: Command[]; visible: boolean; selectedIndex: number }) {
  if (!props.visible || props.commands.length === 0) {
    return null
  }
  const pageSize = 12
  const selectedIndex = Math.min(Math.max(props.selectedIndex, 0), props.commands.length - 1)
  const startIndex = Math.max(0, Math.min(selectedIndex - Math.floor(pageSize / 2), Math.max(props.commands.length - pageSize, 0)))
  const visibleCommands = props.commands.slice(startIndex, startIndex + pageSize)
  return (
    <Box flexDirection="column" borderStyle="round" borderColor="gray" paddingX={1} marginTop={1}>
      <Text color="cyan">Commands</Text>
      {visibleCommands.map((command, index) => (
        <Text
          key={command.name}
          color={startIndex + index === selectedIndex ? 'black' : undefined}
          backgroundColor={startIndex + index === selectedIndex ? 'cyan' : undefined}
        >
          {startIndex + index === selectedIndex ? '> ' : '  '}
          /{command.name}{command.argumentHint ? ` ${command.argumentHint}` : ''} — {command.description}
        </Text>
      ))}
      {props.commands.length > pageSize ? (
        <Text color="gray">  {selectedIndex + 1}/{props.commands.length}</Text>
      ) : null}
    </Box>
  )
}
