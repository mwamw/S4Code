import React from 'react'
import { AppStateProvider } from '../state/AppState'
import type { AppState } from '../state/AppStateStore'
import type { Store } from '../state/store'
import { ThemeProvider } from '../theme/ThemeProvider'

export function App(props: { initialState: AppState; store?: Store<AppState>; children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <AppStateProvider initialState={props.initialState} store={props.store}>
        {props.children}
      </AppStateProvider>
    </ThemeProvider>
  )
}
