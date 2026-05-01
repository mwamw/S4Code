import React, { useEffect, useState } from 'react'
import { Box, Text, Static, useStdout } from 'ink'
import { useAppState } from '../state/AppState'
import { TranscriptView, Card } from './TranscriptView'
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
  const { stdout } = useStdout()
  const [rows, setRows] = useState(stdout.rows || 24)

  useEffect(() => {
    const onResize = () => setRows(stdout.rows)
    stdout.on('resize', onResize)
    return () => {
      stdout.off('resize', onResize)
    }
  }, [stdout])

  const committedCards = useAppState(state => {
    return state.transcript.committedCards || state.transcript.cards || []
  }, equalCards)

  const liveCards = useAppState(state => {
    return [
      state.transcript.liveRoundCard,
      state.transcript.liveThinkingCard,
      state.transcript.liveAssistantCard,
      ...Object.values(state.transcript.liveToolCards || {}),
    ].filter((card): card is TranscriptCard => Boolean(card))
  }, equalCards)

  // Reserve ~5 lines for the composer, footer, and padding
  const maxLiveHeight = Math.max(5, rows - 5)
  
  // Estimate height: title (1 line) + body lines + margin bottom (1 line)
  const estimatedLiveLines = liveCards.reduce((acc, card) => {
    const bodyLines = String(card.body || '').split('\n').length
    return acc + bodyLines + 2 // title + body + margin
  }, 0)

  const isOverflowing = estimatedLiveLines > maxLiveHeight

  return (
    <Box flexDirection="column" flexGrow={1} marginRight={1}>
      <Static items={committedCards}>
        {card => <Card key={card.id} card={card} />}
      </Static>
      {committedCards.length === 0 && <Text bold color="cyan">S4Code</Text>}
      <Box 
        flexDirection="column" 
        overflow="hidden" 
        justifyContent="flex-end"
        height={isOverflowing ? maxLiveHeight : undefined}
      >
        <TranscriptView cards={liveCards} />
      </Box>
    </Box>
  )
}
