import React from 'react'
import { Box, Text, useStdout } from 'ink'
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

type MarkdownBlock =
  | { type: 'blank'; text: string }
  | { type: 'heading'; text: string; level: number }
  | { type: 'bullet'; text: string; marker: string; indent: number; checked?: boolean }
  | { type: 'quote'; text: string }
  | { type: 'code'; text: string; lang: string }
  | { type: 'table'; rows: string[][] }
  | { type: 'rule'; text: string }
  | { type: 'text'; text: string }

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

function looksLikeMarkdown(content: string): boolean {
  const text = content.trim()
  if (!text) {
    return false
  }
  return /^#{1,6}\s/m.test(text)
    || /^\s*[-*+]\s/m.test(text)
    || /^\d+\.\s/m.test(text)
    || /^>\s/m.test(text)
    || /```/.test(text)
    || /`[^`]+`/.test(text)
    || /\*\*[^*]+\*\*/.test(text)
    || /__[^_]+__/.test(text)
    || /~~[^~]+~~/.test(text)
    || /\[[^\]]+\]\([^)]+\)/.test(text)
    || /^\s*\|.*\|\s*$/m.test(text)
    || /^\s*-{3,}\s*$/m.test(text)
}

function looksLikeJson(content: string): boolean {
  const text = content.trim()
  return (text.startsWith('{') && text.endsWith('}')) || (text.startsWith('[') && text.endsWith(']'))
}

function parseTableRow(line: string): string[] | null {
  const trimmed = line.trim()
  if (!trimmed.startsWith('|') || !trimmed.endsWith('|')) {
    return null
  }
  return trimmed.slice(1, -1).split('|').map(cell => cell.trim())
}

function isTableSeparator(line: string): boolean {
  const row = parseTableRow(line)
  return Boolean(row?.length && row.every(cell => /^:?-{3,}:?$/.test(cell)))
}

function parseMarkdownBlocks(content: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = []
  const lines = content.split('\n')
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] || ''
    const fence = line.match(/^```([^\s`]*)\s*$/)
    if (fence) {
      const codeLines: string[] = []
      index += 1
      while (index < lines.length && !/^```\s*$/.test(lines[index] || '')) {
        codeLines.push(lines[index] || '')
        index += 1
      }
      blocks.push({ type: 'code', lang: fence[1] || '', text: codeLines.join('\n') })
      continue
    }
    if (!line.trim()) {
      blocks.push({ type: 'blank', text: '' })
      continue
    }
    const heading = line.match(/^(#{1,6})\s+(.*)$/)
    if (heading) {
      blocks.push({ type: 'heading', level: heading[1].length, text: heading[2] || '' })
      continue
    }
    if (/^\s*-{3,}\s*$/.test(line)) {
      blocks.push({ type: 'rule', text: '' })
      continue
    }
    const tableRow = parseTableRow(line)
    if (tableRow) {
      const rows: string[][] = []
      while (index < lines.length) {
        const nextLine = lines[index] || ''
        if (isTableSeparator(nextLine)) {
          index += 1
          continue
        }
        const row = parseTableRow(nextLine)
        if (!row) {
          index -= 1
          break
        }
        rows.push(row)
        index += 1
      }
      blocks.push({ type: 'table', rows })
      continue
    }
    const bullet = line.match(/^(\s*)([-*+]|\d+\.)\s+(.*)$/)
    if (bullet) {
      const rawText = bullet[3] || ''
      const checkbox = rawText.match(/^\[([ xX])\]\s+(.*)$/)
      blocks.push({
        type: 'bullet',
        indent: Math.floor((bullet[1] || '').length / 2),
        marker: bullet[2] || '-',
        text: checkbox ? checkbox[2] || '' : rawText,
        checked: checkbox ? checkbox[1].toLowerCase() === 'x' : undefined,
      })
      continue
    }
    const quote = line.match(/^\s*>\s?(.*)$/)
    if (quote) {
      blocks.push({ type: 'quote', text: quote[1] || '' })
      continue
    }
    blocks.push({ type: 'text', text: line })
  }
  return blocks
}

function renderInline(text: string, key: string): React.ReactNode[] {
  const pattern = /(`[^`]+`|\*\*[^*\n]+\*\*|__[^_\n]+__|~~[^~\n]+~~|\[[^\]\n]+\]\([^)]+\)|\*[^*\n]+\*|_[^_\n]+_)/g
  const nodes: React.ReactNode[] = []
  let cursor = 0
  let match: RegExpExecArray | null
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) {
      nodes.push(<Text key={`${key}-plain-${cursor}`}>{text.slice(cursor, match.index)}</Text>)
    }
    const part = match[0]
    if (part.startsWith('`') && part.endsWith('`')) {
      nodes.push(
        <Text key={`${key}-code-${match.index}`} color="cyan">
          {part.slice(1, -1)}
        </Text>,
      )
    } else if ((part.startsWith('**') && part.endsWith('**')) || (part.startsWith('__') && part.endsWith('__'))) {
      nodes.push(
        <Text key={`${key}-bold-${match.index}`} bold>
          {part.slice(2, -2)}
        </Text>,
      )
    } else if (part.startsWith('~~') && part.endsWith('~~')) {
      nodes.push(
        <Text key={`${key}-strike-${match.index}`} strikethrough color="gray">
          {part.slice(2, -2)}
        </Text>,
      )
    } else if (part.startsWith('[')) {
      const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/)
      nodes.push(
        <Text key={`${key}-link-${match.index}`}>
          <Text color="cyan" underline>{link?.[1] || part}</Text>
          {link?.[2] ? <Text color="gray"> ({link[2]})</Text> : null}
        </Text>,
      )
    } else if ((part.startsWith('*') && part.endsWith('*')) || (part.startsWith('_') && part.endsWith('_'))) {
      nodes.push(
        <Text key={`${key}-italic-${match.index}`} italic>
          {part.slice(1, -1)}
        </Text>,
      )
    } else {
      nodes.push(<Text key={`${key}-raw-${match.index}`}>{part}</Text>)
    }
    cursor = match.index + part.length
  }
  if (cursor < text.length || nodes.length === 0) {
    nodes.push(<Text key={`${key}-plain-tail`}>{text.slice(cursor)}</Text>)
  }
  return nodes
}

function renderTable(rows: string[][], key: string): React.ReactNode {
  const widths: number[] = []
  for (const row of rows) {
    row.forEach((cell, index) => {
      widths[index] = Math.max(widths[index] || 0, cell.length)
    })
  }
  return (
    <Box key={key} flexDirection="column">
      {rows.map((row, rowIndex) => (
        <Text key={`${key}-row-${rowIndex}`}>
          {row.map((cell, cellIndex) => {
            const padded = cell.padEnd(widths[cellIndex] || cell.length)
            return (
              <Text key={`${key}-cell-${rowIndex}-${cellIndex}`} color={rowIndex === 0 ? 'cyan' : undefined}>
                {cellIndex === 0 ? '' : '  '}
                {renderInline(padded, `${key}-cell-${rowIndex}-${cellIndex}`)}
              </Text>
            )
          })}
        </Text>
      ))}
    </Box>
  )
}

function renderPlainLines(content: string, keyPrefix: string, color?: string): React.ReactNode[] {
  return content.split('\n').map((line, index) => (
    <Text key={`${keyPrefix}-${index}`} color={color}>{line}</Text>
  ))
}

function renderHighlightedCode(text: string, keyPrefix: string, options: { defaultColor?: string; backgroundColor?: string } = {}): React.ReactNode[] {
  const tokenPattern = /(\/\/.*|#.*|\/\*.*?\*\/|"(?:\\.|[^"])*"|'(?:\\.|[^'])*'|`(?:\\.|[^`])*`|\b(?:async|await|class|const|def|else|export|finally|for|from|function|if|import|interface|let|return|type|while|try|catch|public|private|protected|static|new|throw|true|false|null|None|self|this)\b|\b\d+(?:\.\d+)?\b)/g
  const nodes: React.ReactNode[] = []
  let cursor = 0
  let match: RegExpExecArray | null
  while ((match = tokenPattern.exec(text)) !== null) {
    if (match.index > cursor) {
      nodes.push(
        <Text key={`${keyPrefix}-plain-${cursor}`} color={options.defaultColor} backgroundColor={options.backgroundColor}>
          {text.slice(cursor, match.index)}
        </Text>,
      )
    }
    const token = match[0]
    let color = options.defaultColor
    if (token.startsWith('//') || token.startsWith('#') || token.startsWith('/*')) {
      color = 'gray'
    } else if (token.startsWith('"') || token.startsWith("'") || token.startsWith('`')) {
      color = 'green'
    } else if (/^\d/.test(token)) {
      color = 'yellow'
    } else {
      color = 'magenta'
    }
    nodes.push(
      <Text key={`${keyPrefix}-token-${match.index}`} color={color} backgroundColor={options.backgroundColor}>
        {token}
      </Text>,
    )
    cursor = match.index + token.length
  }
  if (cursor < text.length || nodes.length === 0) {
    nodes.push(
      <Text key={`${keyPrefix}-plain-tail`} color={options.defaultColor} backgroundColor={options.backgroundColor}>
        {text.slice(cursor)}
      </Text>,
    )
  }
  return nodes
}

function renderCodeBlock(text: string, lang: string, key: string): React.ReactNode {
  const label = lang ? `\`\`\`${lang}` : '```'
  return (
    <Box key={key} flexDirection="column">
      <Text color="gray">{label}</Text>
      {text.split('\n').map((line, index) => (
        <Text key={`${key}-line-${index}`}>{renderHighlightedCode(line, `${key}-line-${index}`, { defaultColor: 'white' })}</Text>
      ))}
      <Text color="gray">```</Text>
    </Box>
  )
}

function renderMarkdown(content: string, keyPrefix: string): React.ReactNode[] {
  return parseMarkdownBlocks(content).map((block, index) => {
    const key = `${keyPrefix}-md-${index}`
    if (block.type === 'blank') {
      return <Text key={key}> </Text>
    }
    if (block.type === 'heading') {
      return (
        <Text key={key} bold color="cyan">
          {renderInline(block.text, key)}
        </Text>
      )
    }
    if (block.type === 'bullet') {
      const marker = block.checked === undefined
        ? (/\d+\./.test(block.marker) ? block.marker : '•')
        : block.checked ? '[x]' : '[ ]'
      return (
        <Text key={key}>
          {'  '.repeat(block.indent)}{marker} {renderInline(block.text, key)}
        </Text>
      )
    }
    if (block.type === 'quote') {
      return <Text key={key} color="gray">│ {renderInline(block.text, key)}</Text>
    }
    if (block.type === 'table') {
      return renderTable(block.rows, key)
    }
    if (block.type === 'rule') {
      return <Text key={key} color="gray">────────────────</Text>
    }
    if (block.type === 'code') {
      if (block.lang.toLowerCase() === 'diff') {
        return renderStandaloneDiff(block.text, key)
      }
      return renderCodeBlock(block.text, block.lang, key)
    }
    return <Text key={key}>{renderInline(block.text, key)}</Text>
  })
}

function renderStandaloneDiff(diffText: string, keyPrefix: string): React.ReactNode {
  return (
    <Box key={keyPrefix} flexDirection="column">
      {diffText.split('\n').map((line, index) => renderDiffLine(line, `${keyPrefix}-line-${index}`))}
    </Box>
  )
}

function renderDiffPreludeLine(line: string, key: string): React.ReactNode {
  if (line.startsWith('diff --git')) {
    return <Text key={key} bold color="cyan">{line}</Text>
  }
  if (line.startsWith('new file mode') || line.startsWith('+++ ')) {
    return <Text key={key} color="green">{line}</Text>
  }
  if (line.startsWith('--- ')) {
    return <Text key={key} color="red">{line}</Text>
  }
  return <Text key={key} color="gray">{line}</Text>
}

function renderDiffLine(line: string, key: string): React.ReactNode {
  if (line.startsWith('+') && !line.startsWith('+++')) {
    const backgroundColor = '#052e16'
    return (
      <Text key={key}>
        <Text bold color="green" backgroundColor={backgroundColor}>+</Text>
        {renderHighlightedCode(line.slice(1), `${key}-add`, { defaultColor: '#bbf7d0', backgroundColor })}
      </Text>
    )
  }
  if (line.startsWith('-') && !line.startsWith('---')) {
    const backgroundColor = '#3f1111'
    return (
      <Text key={key}>
        <Text bold color="red" backgroundColor={backgroundColor}>-</Text>
        {renderHighlightedCode(line.slice(1), `${key}-del`, { defaultColor: '#fecaca', backgroundColor })}
      </Text>
    )
  }
  if (line.startsWith(' ')) {
    return (
      <Text key={key}>
        <Text color="gray"> </Text>
        {renderHighlightedCode(line.slice(1), `${key}-ctx`)}
      </Text>
    )
  }
  if (line.startsWith('\\')) {
    return <Text key={key} italic color="gray">{line}</Text>
  }
  return <Text key={key}>{line}</Text>
}

function renderDiff(card: TranscriptCard, keyPrefix: string): React.ReactNode[] {
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
  const label = String(diffPayload.relative_path || diffPayload.file_path || '').trim()
  const nodes: React.ReactNode[] = []
  if (summary) {
    nodes.push(<Text key={`${keyPrefix}-summary`} color="white">{summary}</Text>)
  }
  if (label || parsed.prelude.some(line => line.trim())) {
    nodes.push(
      <Box key={`${keyPrefix}-prelude`} flexDirection="column" borderStyle="round" borderColor="gray" paddingX={1}>
        <Text color="cyan">Changed File</Text>
        {label ? <Text color="blue">{label}</Text> : null}
        {parsed.prelude
          .filter(line => line.trim())
          .map((line, index) => renderDiffPreludeLine(line, `${keyPrefix}-prelude-${index}`))}
      </Box>,
    )
  }
  const visibleHunks = parsed.hunks.slice(0, MAX_DIFF_HUNKS_RENDERED)
  for (const [hunkIndex, hunk] of visibleHunks.entries()) {
    const visibleLines = hunk.lines.slice(0, MAX_DIFF_LINES_PER_HUNK)
    nodes.push(
      <Box key={`${keyPrefix}-hunk-${hunkIndex}`} flexDirection="column" borderStyle="round" borderColor="gray" paddingX={1}>
        <Text color="cyan">{hunk.header}</Text>
        {visibleLines.map((line, index) => renderDiffLine(line, `${keyPrefix}-hunk-${hunkIndex}-${index}`))}
      </Box>,
    )
    const hiddenLines = Math.max(hunk.lines.length - visibleLines.length, 0)
    if (hiddenLines > 0) {
      nodes.push(
        <Text key={`${keyPrefix}-hunk-${hunkIndex}-hidden`} color="gray">
          ... {hiddenLines} more line(s) hidden in this hunk
        </Text>,
      )
    }
  }
  const hiddenHunks = Math.max(parsed.hunks.length - visibleHunks.length, 0)
  if (hiddenHunks > 0) {
    nodes.push(<Text key={`${keyPrefix}-hidden-hunks`} color="gray">... {hiddenHunks} more hunk(s) hidden</Text>)
  }
  return nodes
}

function renderBody(card: TranscriptCard): React.ReactNode[] {
  const diffNodes = renderDiff(card, card.id)
  if (diffNodes.length > 0) {
    return diffNodes
  }
  const content = String(card.body || '')
  if (!content) {
    return [<Text key={`${card.id}-empty`}> </Text>]
  }
  if (['assistant', 'system'].includes(card.kind) && looksLikeMarkdown(content)) {
    return renderMarkdown(card.status === 'streaming' && content.split('```').length % 2 === 0 ? `${content}\n\`\`\`` : content, card.id)
  }
  if (looksLikeJson(content)) {
    try {
      return [renderCodeBlock(JSON.stringify(JSON.parse(content), null, 2), 'json', `${card.id}-json`)]
    } catch {
      return renderPlainLines(content, card.id, cardColor(card.kind))
    }
  }
  if (content.includes('diff --git') || content.startsWith('--- ') || content.startsWith('@@ ')) {
    return [renderStandaloneDiff(content, `${card.id}-raw-diff`)]
  }
  return renderPlainLines(content, card.id, card.kind === 'assistant' ? undefined : cardColor(card.kind))
}

function checkpointText(card: TranscriptCard): string {
  const checkpoints = card.metadata?.checkpoints
  if (!Array.isArray(checkpoints) || checkpoints.length === 0) {
    return ''
  }
  const labels = checkpoints.slice(-2).map(item => {
    if (!item || typeof item !== 'object') {
      return ''
    }
    const record = item as Record<string, unknown>
    const checkpointId = String(record.checkpoint_id || '').trim()
    const label = String(record.label || '').trim()
    if (checkpointId && label) {
      return `${checkpointId} · ${label}`
    }
    return checkpointId
  }).filter(Boolean)
  if (checkpoints.length > 2) {
    labels.unshift(`+${checkpoints.length - 2}`)
  }
  return labels.join('  ')
}

function cardsEqual(left: TranscriptCard, right: TranscriptCard): boolean {
  return left.id === right.id
    && left.kind === right.kind
    && left.status === right.status
    && left.title === right.title
    && left.body === right.body
    && left.metadata === right.metadata
}

export const Card = React.memo(function Card(props: { card: TranscriptCard; separatorWidth: number }) {
  const { card, separatorWidth } = props
  if (card.kind === 'separator') {
    return (
      <Box width="100%">
        <Text color="gray">{'─'.repeat(separatorWidth)}</Text>
      </Box>
    )
  }
  const checkpoint = checkpointText(card)
  return (
    <Box flexDirection="column" marginBottom={1}>
      <Text color={cardColor(card.kind)}>
        {card.title}
        {card.status ? ` [${card.status.toUpperCase()}]` : ''}
      </Text>
      {renderBody(card)}
      {typeof card.metadata?.footer_left === 'string' && card.metadata.footer_left.trim() ? (
        <Text color="gray">{card.metadata.footer_left.trim()}</Text>
      ) : null}
      {checkpoint ? <Text color="yellow">{checkpoint}</Text> : null}
    </Box>
  )
}, (left, right) => left.separatorWidth === right.separatorWidth && cardsEqual(left.card, right.card))

export function TranscriptView(props: { cards: TranscriptCard[] }) {
  const { stdout } = useStdout()
  const separatorWidth = Math.max(24, Math.min((stdout?.columns || 80) - 2, 160))
  return (
    <Box flexDirection="column">
      {props.cards.map(card => <Card key={card.id} card={card} separatorWidth={separatorWidth} />)}
    </Box>
  )
}
