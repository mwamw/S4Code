import { expect, test } from 'bun:test'
import React from 'react'
import { Box, render } from 'ink'
import { PassThrough } from 'node:stream'
import { stripVTControlCharacters } from 'node:util'
import stringWidth from 'string-width'
import type { ReadStream, WriteStream } from 'node:tty'
import { CommandPalette } from '../src/components/CommandPalette'
import type { PaletteEntry } from '../src/state/AppStateStore'

function paletteRenderer() {
  const stdout = Object.assign(new PassThrough(), { columns: 120, rows: 24, isTTY: true })
  const stdin = new PassThrough()
  const stderr = new PassThrough()
  let frame = ''
  stdout.on('data', chunk => { frame = stripVTControlCharacters(chunk.toString()) })
  stderr.resume()
  const app = render(<Box />, { stdout: stdout as unknown as WriteStream, stdin: stdin as unknown as ReadStream,
    stderr: stderr as unknown as WriteStream, debug: true, patchConsole: false, exitOnCtrlC: false })
  return {
    show: (entries: PaletteEntry[], width: number | '100%', hint = '') => {
      app.rerender(<Box width={width}><CommandPalette visible entries={entries} selectedIndex={0} hint={hint} /></Box>)
      return frame.split('\n').filter(line => line.startsWith('│'))
    },
    resize: (columns: number) => {
      stdout.columns = columns
      stdout.emit('resize')
      return frame.split('\n').filter(line => line.startsWith('│'))
    },
    dispose: () => { app.unmount(); stdout.destroy(); stdin.destroy(); stderr.destroy() },
  }
}

test('command rows truncate to the available layout width and reflow after resizing', () => {
  const renderer = paletteRenderer()
  const entries: PaletteEntry[] = ['model', 'session', 'permissions'].map(name => ({
    label: `/${name}`, description: 'A very long description '.repeat(20),
    insertText: `/${name} `, executeText: `/${name}`, mode: 'insert',
  }))
  try {
    for (const width of [80, 36, 64, 20]) {
      const rows = renderer.show(entries, width, 'A long argument prompt '.repeat(20))
      // Title, three entries, hint, footer: never extra rows for wrapped text.
      expect(rows).toHaveLength(6)
      expect(rows.every(row => row.length === width)).toBe(true)
      for (const row of rows.slice(1, 5)) expect(row).toContain('…')
      expect(rows[1]).toContain('> /model')
    }
  } finally { renderer.dispose() }
})

test('an open menu responds to terminal resize without another keystroke', () => {
  const renderer = paletteRenderer()
  try {
    renderer.show([{ label: '/model', description: 'Model description '.repeat(20), insertText: '/model ', executeText: '/model ', mode: 'insert' }], '100%')
    for (const width of [42, 90]) {
      const rows = renderer.resize(width)
      expect(rows).toHaveLength(3)
      expect(rows[1]).toContain('…')
      expect(rows.every(row => stringWidth(row) === width)).toBe(true)
    }
  } finally { renderer.dispose() }
})

test('model names and descriptions with line breaks, ANSI escapes or wide characters stay on one row', () => {
  const renderer = paletteRenderer()
  const entries: PaletteEntry[] = [
    { label: 'model\nname', description: 'first\r\nsecond\tthird\x1b[31m red\x1b[0m', insertText: '', executeText: '1', mode: 'execute' },
    { label: '中文模型', description: '推理能力 🚀 '.repeat(30), insertText: '', executeText: '2', mode: 'execute' },
    { label: 'a-long-model-name-'.repeat(20), description: '', insertText: '', executeText: '3', mode: 'execute' },
  ]
  try {
    const rows = renderer.show(entries, 52)
    expect(rows).toHaveLength(5)
    expect(rows[1]).toContain('> model name — first second third red')
    expect(rows[2]).toContain('中文模型')
    expect(rows[2]).toContain('…')
    expect(rows[3]).toContain('…')
    for (const row of rows) {
      expect(row).toMatch(/│$/)
      expect(stringWidth(row)).toBe(52)
    }
  } finally { renderer.dispose() }
})
