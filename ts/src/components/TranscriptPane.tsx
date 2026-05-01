import React from 'react'
import { Box, Text } from 'ink'
import { useAppState } from '../state/AppState'
import { getVisibleTranscriptCards } from '../state/transcript'
import { TranscriptView } from './TranscriptView'
import type { TranscriptCard } from '../state/AppStateStore'

function equalCards(left: TranscriptCard[], right: TranscriptCard[]): boolean {
  if (left.length !== right.length) {
    return false
  }
  for (let index = 0; index < left.length; index += 1) {
    const leftCard = left[index]
    const rightCard = right[index]
    if (
      leftCard.id !== rightCard.id
      || leftCard.status !== rightCard.status
      || leftCard.title !== rightCard.title
      || leftCard.body !== rightCard.body
    ) {
      return false
    }
  }
  return true
}

export function TranscriptPane() {
  const cards = useAppState(state => {
    const visible = getVisibleTranscriptCards(state.transcript)
    return state.runtime.autoFollowTranscript ? visible.slice(-80) : visible
  }, equalCards)
  return (
    <Box flexDirection="column" flexGrow={1} marginRight={1}>
      <Text bold color="cyan">S4Code</Text>
      <TranscriptView cards={cards} />
    </Box>
  )
}
