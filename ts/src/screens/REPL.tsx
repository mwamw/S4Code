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
        void props.engine.pollRuntime()
      }
    }, 1000)
    return () => clearInterval(timer)
  }, [props.engine, busy])

  useInput((value, key) => {
    if (key.ctrl && value === 'c') {
      void props.engine.close().finally(exit)
    }
  })

  return (
    <Box flexDirection="column" width="100%">
      <Box flexDirection="row" width="100%">
        <TranscriptPane />
        <SidebarPane />
      </Box>
      <ComposerPane engine={props.engine} />
      <FooterPane />
    </Box>
  )
}
