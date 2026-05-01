import React from 'react'
import { useInput } from 'ink'
import { CommandPalette } from './CommandPalette'
import { PromptInput } from './PromptInput'
import { useAppState, useSetAppState } from '../state/AppState'
import type { QueryEngine } from '../query/QueryEngine'

export function ComposerPane(props: { engine: QueryEngine; onExit?: () => void }) {
  const busy = useAppState(state => state.runtime.busy)
  const input = useAppState(state => state.ui.input)
  const selectedIndex = useAppState(state => state.palette.selection)
  const setAppState = useSetAppState()
  const matches = props.engine.getPaletteCommands(input)
  const paletteVisible = input.trim().startsWith('/') && matches.length > 0
  const boundedSelection = Math.min(Math.max(selectedIndex, 0), Math.max(matches.length - 1, 0))

  useInput((_value, key) => {
    if (!paletteVisible) {
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
          selection: Math.min(matches.length - 1, boundedSelection + 1),
        },
      }))
      return
    }
    if (key.tab) {
      const command = matches[boundedSelection]
      if (!command) {
        return
      }
      setAppState(prev => ({
        ...prev,
        ui: {
          ...prev.ui,
          input: `/${command.name}${command.argumentHint && command.argumentHint.startsWith('<') ? ' ' : ''}`,
        },
        palette: {
          ...prev.palette,
          selection: 0,
        },
      }))
    }
  })

  return (
    <>
      <CommandPalette commands={matches} visible={paletteVisible} selectedIndex={boundedSelection} />
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
            palette: {
              ...prev.palette,
              selection: 0,
            },
          }))
        }}
        onSubmit={value => {
          if (busy) {
            return
          }
          const commandBody = value.trim().replace(/^\//, '')
          const shouldUseSelection = paletteVisible
            && matches[boundedSelection]
            && !commandBody.includes(' ')
            && commandBody !== matches[boundedSelection].name
          const submitted = shouldUseSelection
            ? `/${matches[boundedSelection].name}`
            : value
          setAppState(prev => ({
            ...prev,
            ui: {
              ...prev.ui,
              input: '',
            },
            palette: {
              ...prev.palette,
              selection: 0,
            },
          }))
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
