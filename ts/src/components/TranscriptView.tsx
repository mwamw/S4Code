import React from 'react'
import { Box, Text } from 'ink'
import type { TranscriptCard } from '../state/AppStateStore'

const MAX_DIFF_HUNKS_RENDERED = 2
const MAX_DIFF_LINES_PER_HUNK = 8

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

type ParsedDiffHunk = {
  header: string
  lines: string[]
}

type ParsedUnifiedDiff = {
  prelude: string[]
  hunks: ParsedDiffHunk[]
}

function extractDiffPayload(card: TranscriptCard): Record<string, unknown> | null {
  const payload = card.metadata?.diff
  if (!payload || typeof payload !== 'object') {
    return null
  }
  const diff = payload as Record<string, unknown>
  const unified = String(diff.unified || '').trim()
  return unified ? diff : null
}

function parseUnifiedDiff(diffText: string): ParsedUnifiedDiff {
  const prelude: string[] = []
  const hunks: ParsedDiffHunk[] = []
  let currentHunk: ParsedDiffHunk | null = null
  for (const line of diffText.split('\n')) {
    if (line.startsWith('@@ ')) {
      currentHunk = { header: line, lines: [] }
      hunks.push(currentHunk)
      continue
    }
    if (currentHunk) {
      currentHunk.lines.push(line)
      continue
    }
    prelude.push(line)
  }
  return { prelude, hunks }
}

function renderDiffLines(card: TranscriptCard): string[] {
  const diffPayload = extractDiffPayload(card)
  if (!diffPayload) {
    return []
  }
  const unified = String(diffPayload.unified || '').trim()
  if (!unified) {
    return []
  }
  const parsed = parseUnifiedDiff(unified)
  const summary = String(card.body || '').trim()
  const lines: string[] = []
  if (summary) {
    lines.push(summary)
  }
  const label = String(diffPayload.relative_path || diffPayload.file_path || '').trim()
  if (label) {
    lines.push(`Changed File: ${label}`)
  }
  for (const line of parsed.prelude) {
    const trimmed = line.trim()
    if (trimmed) {
      lines.push(trimmed)
    }
  }
  const visibleHunks = parsed.hunks.slice(0, MAX_DIFF_HUNKS_RENDERED)
  for (const hunk of visibleHunks) {
    lines.push(hunk.header)
    const visibleLines = hunk.lines.slice(0, MAX_DIFF_LINES_PER_HUNK)
    lines.push(...visibleLines)
    const hiddenLines = Math.max(hunk.lines.length - visibleLines.length, 0)
    if (hiddenLines > 0) {
      lines.push(`... ${hiddenLines} more line(s) hidden in this hunk`)
    }
  }
  const hiddenHunks = Math.max(parsed.hunks.length - visibleHunks.length, 0)
  if (hiddenHunks > 0) {
    lines.push(`... ${hiddenHunks} more hunk(s) hidden`)
  }
  return lines
}

function renderBodyLines(card: TranscriptCard): string[] {
  const diffLines = renderDiffLines(card)
  if (diffLines.length > 0) {
    return diffLines
  }
  return String(card.body || '').split('\n')
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
      {renderBodyLines(card)
        .map((line, index) => (
          <Text key={`${card.id}-${index}`}>{line}</Text>
        ))}
      {typeof card.metadata?.footer_left === 'string' && card.metadata.footer_left.trim() ? (
        <Text color="gray">{card.metadata.footer_left.trim()}</Text>
      ) : null}
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
