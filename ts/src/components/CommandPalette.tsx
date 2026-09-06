import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Box, Text, measureElement, useStdout, type DOMElement } from 'ink'
import { stripVTControlCharacters } from 'node:util'
import stringWidth from 'string-width'
import type { PaletteEntry } from '../state/AppStateStore'

const graphemes = new Intl.Segmenter(undefined, { granularity: 'grapheme' })

function truncateLine(text: string, width: number): string {
  if (width < 1) return ''
  if (stringWidth(text) <= width) return text
  let result = ''
  let columns = 0
  // Ink 5's truncator can overrun with emoji. Slice by terminal columns without
  // splitting a grapheme, before passing the already bounded text to Ink.
  for (const { segment } of graphemes.segment(text)) {
    columns += stringWidth(segment)
    if (columns > width - 1) break
    result += segment
  }
  return `${result.trimEnd()}…`
}

/** Constrain every menu row, including server-provided labels and descriptions. */
function MenuLine(props: { children: string; width: number; prefix?: string; color?: string; backgroundColor?: string }) {
  const text = (props.prefix || '') + stripVTControlCharacters(props.children).replace(/[\s\u0000-\u001f\u007f-\u009f]+/gu, ' ').trim()
  return (
    <Box width="100%" minWidth={0} height={1} flexShrink={0}>
      <Text color={props.color} backgroundColor={props.backgroundColor} wrap="truncate-end">{truncateLine(text, props.width)}</Text>
    </Box>
  )
}

export function CommandPalette(props: { entries: PaletteEntry[]; visible: boolean; selectedIndex: number; loading?: boolean; title?: string; hint?: string }) {
  const element = useRef<DOMElement>(null)
  const { stdout } = useStdout()
  const [width, setWidth] = useState(0)
  const measure = useCallback(() => {
    if (element.current) setWidth(Math.max(0, Math.floor(measureElement(element.current).width) - 4))
  }, [])
  // Measure the layout container (not just stdout), including on parent resize.
  useLayoutEffect(measure)
  useEffect(() => {
    stdout.on('resize', measure)
    return () => { stdout.off('resize', measure) }
  }, [stdout, measure])
  if (!props.visible) {
    return null
  }
  const pageSize = 5
  const selectedIndex = Math.min(Math.max(props.selectedIndex, 0), props.entries.length - 1)
  const startIndex = Math.max(0, Math.min(selectedIndex - Math.floor(pageSize / 2), Math.max(props.entries.length - pageSize, 0)))
  const visibleEntries = props.entries.slice(startIndex, startIndex + pageSize)
  const hiddenAfter = Math.max(props.entries.length - startIndex - visibleEntries.length, 0)
  return (
    <Box ref={element} width="100%" minWidth={0} flexDirection="column" borderStyle="round" borderColor="gray" paddingX={1} marginTop={1} flexShrink={0}>
      <MenuLine width={width} color="cyan">{props.title || 'Commands'}</MenuLine>
      {props.loading ? <MenuLine width={width} color="gray">Loading choices...</MenuLine> : null}
      {startIndex > 0 ? (
        <MenuLine width={width} color="gray">{`… ${startIndex} earlier item(s)`}</MenuLine>
      ) : null}
      {visibleEntries.map((entry, index) => (
        <MenuLine
          key={`${entry.executeText}-${entry.label}`}
          width={width}
          color={startIndex + index === selectedIndex ? 'black' : undefined}
          backgroundColor={startIndex + index === selectedIndex ? 'cyan' : undefined}
          prefix={startIndex + index === selectedIndex ? '> ' : '  '}
        >
          {`${entry.label}${entry.mode === 'insert' ? ' ›' : ''}${entry.description ? ` — ${entry.description}` : ''}`}
        </MenuLine>
      ))}
      {hiddenAfter > 0 ? (
        <MenuLine width={width} color="gray">{`… ${hiddenAfter} more item(s)`}</MenuLine>
      ) : null}
      {!props.loading && props.hint ? <MenuLine width={width} color="gray">{props.hint}</MenuLine> : null}
      <MenuLine width={width} color="gray">↑/↓ select · Enter choose · Tab complete · Esc back</MenuLine>
    </Box>
  )
}
