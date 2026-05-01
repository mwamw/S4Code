import React, { useEffect } from 'react'
import { Box, useApp } from 'ink'
import { useInput } from 'ink'
import { ComposerPane } from '../components/ComposerPane'
import { FooterPane } from '../components/FooterPane'
import { SidebarPane } from '../components/SidebarPane'
import { TranscriptPane } from '../components/TranscriptPane'
import { useAppState } from '../state/AppState'
import type { QueryEngine } from '../query/QueryEngine'

export function REPL(props: { engine: QueryEngine }) {
  const { exit } = useApp()
  const busy = useAppState(state => state.runtime.busy)

  useEffect(() => {
    const timer = setInterval(() => {
      if (!busy) {
        void props.engine.pollRuntime().catch(() => undefined)
      }
    }, 1000)
    const unsubscribeQuit = props.engine.onQuit(exit)
    return () => {
      clearInterval(timer)
      unsubscribeQuit()
    }
  }, [props.engine, busy, exit])

  useInput((value, key) => {
    if (key.ctrl && value === 'c') {
      void props.engine.quit()
    }
  })

  return (
    <Box flexDirection="column" width="100%">
      <Box flexDirection="row" width="100%">
        <TranscriptPane />
        <SidebarPane />
      </Box>
      <FooterPane />
      <ComposerPane engine={props.engine} onExit={exit} />
    </Box>
  )
}
