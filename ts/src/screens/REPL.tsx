import React, { useEffect } from 'react'
import { Box, useApp } from 'ink'
import { useInput } from 'ink'
import { ComposerPane } from '../components/ComposerPane'
import { FooterPane } from '../components/FooterPane'
import { SidebarPane } from '../components/SidebarPane'
import { TranscriptPane } from '../components/TranscriptPane'
import { useAppState, useSetAppState } from '../state/AppState'
import { refreshActiveRoundElapsed } from '../state/transcript'
import type { InkController } from '../controller/InkController'

export function REPL(props: { engine: InkController }) {
  const { exit } = useApp()
  const busy = useAppState(state => state.runtime.busy)
  const setState = useSetAppState()

  useEffect(() => {
    const timer = setInterval(() => {
      if (!busy) {
        void props.engine.pollRuntime().catch(() => undefined)
      } else {
        setState(state => refreshActiveRoundElapsed(state))
      }
    }, 1000)
    const unsubscribeQuit = props.engine.onQuit(exit)
    return () => {
      clearInterval(timer)
      unsubscribeQuit()
    }
  }, [props.engine, busy, exit, setState])

  useInput((value, key) => {
    if (key.ctrl && value === 'c') {
      void props.engine.quit().catch(exit)
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
