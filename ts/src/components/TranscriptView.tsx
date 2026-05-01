import React from 'react'
import { Box, Text } from 'ink'
import type { TranscriptCard } from '../state/AppStateStore'

function cardColor(kind: TranscriptCard['kind']): string {
  switch (kind) {
    case 'user':
      return 'green'
    case 'assistant':
      return 'white'
    case 'thinking':
      return 'yellow'
    case 'tool':
      return 'magenta'
    case 'warning':
      return 'yellow'
    case 'error':
      return 'red'
    case 'round':
      return 'cyan'
    case 'separator':
      return 'gray'
    default:
      return 'blue'
  }
}

export function Card(props: { card: TranscriptCard }) {
  const { card } = props
  if (card.kind === 'separator') {
    return <Text color="gray">────────────────────────────────────────</Text>
  }
  return (
    <Box flexDirection="column" marginBottom={1}>
      <Text color={cardColor(card.kind)}>
        {card.title}
        {card.status ? ` [${card.status.toUpperCase()}]` : ''}
      </Text>
      {String(card.body || '')
        .split('\n')
        .map((line, index) => (
          <Text key={`${card.id}-${index}`}>{line}</Text>
        ))}
    </Box>
  )
}

export function TranscriptView(props: { cards: TranscriptCard[] }) {
  return (
    <Box flexDirection="column">
      {props.cards.map(card => <Card key={card.id} card={card} />)}
    </Box>
  )
}
