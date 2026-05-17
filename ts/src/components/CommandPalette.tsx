import React from 'react'
import { Box, Text } from 'ink'
import type { PaletteEntry } from '../state/AppStateStore'

export function CommandPalette(props: { entries: PaletteEntry[]; visible: boolean; selectedIndex: number; loading?: boolean }) {
  if (!props.visible) {
    return null
  }
  if (props.entries.length === 0) {
    return props.loading
      ? (
          <Box flexDirection="column" borderStyle="round" borderColor="gray" paddingX={1} marginTop={1}>
            <Text color="gray">Commands loading...</Text>
          </Box>
        )
      : null
  }
  const pageSize = 5
  const selectedIndex = Math.min(Math.max(props.selectedIndex, 0), props.entries.length - 1)
  const startIndex = Math.max(0, Math.min(selectedIndex - Math.floor(pageSize / 2), Math.max(props.entries.length - pageSize, 0)))
  const visibleEntries = props.entries.slice(startIndex, startIndex + pageSize)
  const hiddenAfter = Math.max(props.entries.length - startIndex - visibleEntries.length, 0)
  return (
    <Box flexDirection="column" borderStyle="round" borderColor="gray" paddingX={1} marginTop={1}>
      <Text color="cyan">Commands</Text>
      {startIndex > 0 ? (
        <Text color="gray">... {startIndex} earlier item(s)</Text>
      ) : null}
      {visibleEntries.map((entry, index) => (
        <Text
          key={`${entry.executeText}-${entry.label}`}
          color={startIndex + index === selectedIndex ? 'black' : undefined}
          backgroundColor={startIndex + index === selectedIndex ? 'cyan' : undefined}
        >
          {startIndex + index === selectedIndex ? '> ' : '  '}
          {entry.label} — {entry.description}
          {entry.aliases?.length ? `  aliases: ${entry.aliases.map(alias => `/${alias}`).join(', ')}` : ''}
        </Text>
      ))}
      {hiddenAfter > 0 ? (
        <Text color="gray">... {hiddenAfter} more item(s)</Text>
      ) : null}
      {props.entries.length > pageSize ? (
        <Text color="gray">  {selectedIndex + 1}/{props.entries.length}  ↑/↓ select · Enter run · Tab insert</Text>
      ) : null}
    </Box>
  )
}
