import { BridgeClient, BridgeProcess } from '../packages/bridge-client/src/index'
import { InkCoreClient } from './controller/InkCoreClient'
import { getDefaultAppState, type AppState } from './state/AppStateStore'
import { createStore, type Store } from './state/store'
import { InkController } from './controller/InkController'

export async function setup(options: { cwd: string; sessionId?: string | null; transientSession?: boolean }): Promise<{
  bridge: InkCoreClient
  store: Store<AppState>
  engine: InkController
}> {
  const process = new BridgeProcess({ cwd: options.cwd, sessionId: options.sessionId,
    transientSession: Boolean(options.transientSession),
  })
  const bridge = new InkCoreClient(new BridgeClient(process))
  const store = createStore(getDefaultAppState())
  const engine = new InkController({
    bridge,
    getAppState: store.getState,
    setAppState: store.setState,
  })

  try {
    const init = await bridge.init()
    store.setState(() => engine.buildStateFromInit(init))
  } catch (error) {
    bridge.terminate()
    throw error
  }

  return {
    bridge,
    store,
    engine,
  }
}
