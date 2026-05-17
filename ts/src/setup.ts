import { BridgeClient } from './runtime/bridgeClient'
import { BridgeProcess } from './runtime/bridgeProcess'
import { getDefaultAppState, type AppState } from './state/AppStateStore'
import { createStore, type Store } from './state/store'
import { QueryEngine } from './query/QueryEngine'

export async function setup(options: { cwd: string; sessionId?: string | null; transientSession?: boolean }): Promise<{
  bridge: BridgeClient
  store: Store<AppState>
  engine: QueryEngine
}> {
  const process = new BridgeProcess(options.cwd, options.sessionId, {
    transientSession: Boolean(options.transientSession),
    ignoreSessionModelOverrides: Boolean(options.sessionId),
  })
  const bridge = new BridgeClient(process)
  const store = createStore(getDefaultAppState())
  const engine = new QueryEngine({
    bridge,
    getAppState: store.getState,
    setAppState: store.setState,
  })

  const init = await bridge.init()
  store.setState(() => engine.buildStateFromInit(init))

  return {
    bridge,
    store,
    engine,
  }
}
