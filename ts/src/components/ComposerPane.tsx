import React from 'react'
import { useInput } from 'ink'
import { CommandPalette } from './CommandPalette'
import { PromptInput } from './PromptInput'
import { useAppState, useSetAppState } from '../state/AppState'
import type { QueryEngine } from '../query/QueryEngine'

function isQuitInput(value: string): boolean {
  return ['/exit', '/quit', '/q'].includes(value.trim().toLowerCase())
}

export function ComposerPane(props: { engine: QueryEngine; onExit?: () => void }) {
  const busy = useAppState(state => state.runtime.busy)
  const input = useAppState(state => state.ui.input)
  const selectedIndex = useAppState(state => state.palette.selection)
  const entries = useAppState(state => state.palette.entries)
  const paletteLoading = useAppState(state => state.palette.loading)
  const paletteSourceText = useAppState(state => state.palette.sourceText)
  const setAppState = useSetAppState()
  const entriesMatchInput = paletteSourceText === input
  const visibleEntries = entriesMatchInput ? entries : []
  const paletteVisible = input.trim().startsWith('/') && (visibleEntries.length > 0 || paletteLoading)
  const boundedSelection = Math.min(Math.max(selectedIndex, 0), Math.max(visibleEntries.length - 1, 0))

  const updateInput = (value: string, selection = 0) => {
    setAppState(prev => ({
      ...prev,
      ui: {
        ...prev.ui,
        input: value,
      },
      palette: {
        ...prev.palette,
        selection,
      },
    }))
    props.engine.refreshPalette(value)
  }

  useInput((_value, key) => {
    if (key.escape && busy) {
      void props.engine.interrupt()
      return
    }
    if (!paletteVisible) {
      return
    }
    if (key.escape) {
      updateInput('')
      return
    }
    if (key.pageUp) {
      setAppState(prev => ({
        ...prev,
        palette: {
          ...prev.palette,
          selection: Math.max(0, boundedSelection - 10),
        },
      }))
      return
    }
    if (key.pageDown) {
      setAppState(prev => ({
        ...prev,
        palette: {
          ...prev.palette,
          selection: Math.min(visibleEntries.length - 1, boundedSelection + 10),
        },
      }))
      return
    }
    if (key.upArrow) {
      setAppState(prev => ({
        ...prev,
        palette: {
          ...prev.palette,
          selection: Math.max(0, boundedSelection - 1),
        },
      }))
      return
    }
    if (key.downArrow) {
      setAppState(prev => ({
        ...prev,
        palette: {
          ...prev.palette,
          selection: Math.min(visibleEntries.length - 1, boundedSelection + 1),
        },
      }))
      return
    }
    if (key.tab) {
      const entry = visibleEntries[boundedSelection]
      if (!entry) {
        return
      }
      updateInput(entry.insertText)
    }
  })

  return (
    <>
      <CommandPalette entries={visibleEntries} visible={paletteVisible} selectedIndex={boundedSelection} loading={paletteLoading} />
      <PromptInput
        value={input}
        busy={busy}
        onChange={value => {
          updateInput(value)
        }}
        onSubmit={value => {
          if (isQuitInput(value)) {
            updateInput('')
            void props.engine.quit().then(() => {
              props.onExit?.()
            })
            return
          }
          if (busy) {
            return
          }
          const selectedEntry = paletteVisible ? visibleEntries[boundedSelection] : undefined
          if (selectedEntry?.mode === 'insert') {
            updateInput(selectedEntry.insertText)
            return
          }
          const submitted = selectedEntry?.executeText || value
          updateInput('')
          void props.engine.handleInput(submitted).then(result => {
            if (result === 'quit') {
              props.onExit?.()
            }
          })
        }}
      />
    </>
  )
}
