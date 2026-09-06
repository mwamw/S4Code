import React, { useState } from 'react'
import { useInput } from 'ink'
import { CommandPalette } from './CommandPalette'
import { PromptInput } from './PromptInput'
import { useAppState, useSetAppState } from '../state/AppState'
import type { InkController } from '../controller/InkController'

function isQuitInput(value: string): boolean {
  return ['/exit', '/quit', '/q'].includes(value.trim().toLowerCase())
}

export function ComposerPane(props: { engine: InkController; onExit?: () => void }) {
  const busy = useAppState(state => state.runtime.busy)
  const input = useAppState(state => state.ui.input)
  const selectedIndex = useAppState(state => state.palette.selection)
  const entries = useAppState(state => state.palette.entries)
  const paletteLoading = useAppState(state => state.palette.loading)
  const paletteSourceText = useAppState(state => state.palette.sourceText)
  const title = useAppState(state => state.palette.title)
  const hint = useAppState(state => state.palette.hint)
  const parentInput = useAppState(state => state.palette.parentInput)
  const canSubmit = useAppState(state => state.palette.canSubmit)
  const [inputRevision, setInputRevision] = useState(0)
  const setAppState = useSetAppState()
  const entriesMatchInput = paletteSourceText === input
  const visibleEntries = entriesMatchInput ? entries : []
  const paletteVisible = input.trim().startsWith('/') && (visibleEntries.length > 0 || paletteLoading || Boolean(hint))
  const boundedSelection = Math.min(Math.max(selectedIndex, 0), Math.max(visibleEntries.length - 1, 0))

  const updateInput = (value: string, action: 'edit' | 'navigate' = 'edit') => {
    setAppState(prev => ({
      ...prev,
      ui: {
        ...prev.ui,
        input: value,
      },
      palette: {
        ...prev.palette,
        selection: 0,
      },
    }))
    props.engine.refreshPalette(value, action)
  }

  // Completion replaces the input, so reset the editor's internal cursor to its end.
  const replaceInput = (value: string, action: 'edit' | 'navigate' = 'edit') => {
    setInputRevision(revision => revision + 1)
    updateInput(value, action)
  }

  useInput((_value, key) => {
    if (key.escape && busy) {
      void props.engine.interrupt()
      return
    }
    if (!paletteVisible) {
      return
    }
    if (key.escape || (key.tab && key.shift)) {
      replaceInput(parentInput, 'navigate')
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
      replaceInput(entry.insertText)
    }
  })

  return (
    <>
      <CommandPalette entries={visibleEntries} visible={paletteVisible} selectedIndex={boundedSelection} loading={paletteLoading} title={title} hint={hint} />
      <PromptInput
        key={inputRevision}
        value={input}
        busy={busy}
        onChange={value => {
          updateInput(value)
        }}
        onSubmit={value => {
          if (isQuitInput(value)) {
            replaceInput('')
            void props.engine.quit().then(() => {
              props.onExit?.()
            }).catch(() => props.onExit?.())
            return
          }
          if (busy) {
            return
          }
          if (paletteVisible && paletteLoading) return
          const selectedEntry = paletteVisible ? visibleEntries[boundedSelection] : undefined
          if (selectedEntry?.mode === 'insert') {
            replaceInput(selectedEntry.insertText, 'navigate')
            return
          }
          if (!selectedEntry && entriesMatchInput && !canSubmit) return
          const submitted = selectedEntry?.executeText || value
          replaceInput('')
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
