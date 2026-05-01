import React, { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { AppState } from './AppStateStore'
import { createStore, type Store } from './store'

type AppStateStore = Store<AppState>

const AppStoreContext = createContext<AppStateStore | null>(null)

export function AppStateProvider(
  props: {
    children: React.ReactNode
    initialState?: AppState
    store?: AppStateStore
  },
) {
  const [store] = useState(() => props.store ?? createStore(props.initialState as AppState))
  return (
    <AppStoreContext.Provider value={store}>
      {props.children}
    </AppStoreContext.Provider>
  )
}

function useAppStore(): AppStateStore {
  const store = useContext(AppStoreContext)
  if (!store) {
    throw new Error('AppStateProvider is missing')
  }
  return store
}

export function useAppState<T>(
  selector: (state: AppState) => T,
  equals: (left: T, right: T) => boolean = Object.is,
): T {
  const store = useAppStore()
  const selectorRef = useRef(selector)
  const equalsRef = useRef(equals)
  const selectedRef = useRef(selector(store.getState()))
  const [selected, setSelected] = useState(selectedRef.current)

  selectorRef.current = selector
  equalsRef.current = equals

  useEffect(() => {
    return store.subscribe(() => {
      const next = selectorRef.current(store.getState())
      if (equalsRef.current(selectedRef.current, next)) {
        return
      }
      selectedRef.current = next
      setSelected(next)
    })
  }, [store])

  return selected
}

export function useSetAppState(): AppStateStore['setState'] {
  return useAppStore().setState
}

export function useAppStateStore(): AppStateStore {
  return useAppStore()
}
