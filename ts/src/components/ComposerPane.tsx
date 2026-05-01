import React from 'react'
import { CommandPalette } from './CommandPalette'
import { PromptInput } from './PromptInput'
import { useAppState, useSetAppState } from '../state/AppState'
import type { QueryEngine } from '../query/QueryEngine'

export function ComposerPane(props: { engine: QueryEngine }) {
  const busy = useAppState(state => state.runtime.busy)
  const input = useAppState(state => state.ui.input)
  const setAppState = useSetAppState()
  const matches = props.engine.getPaletteCommands(input)

  return (
    <>
      <CommandPalette commands={matches} visible={input.trim().startsWith('/')} />
      <PromptInput
        value={input}
        busy={busy}
        onChange={value => {
          setAppState(prev => ({
            ...prev,
            ui: {
              ...prev.ui,
              input: value,
            },
          }))
        }}
        onSubmit={value => {
          if (busy) {
            return
          }
          setAppState(prev => ({
            ...prev,
            ui: {
              ...prev.ui,
              input: '',
            },
          }))
          void props.engine.handleInput(value)
        }}
      />
    </>
  )
}
