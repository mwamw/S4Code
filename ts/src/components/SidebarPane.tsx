import React from 'react'
import { useAppState } from '../state/AppState'
import { Sidebar } from './Sidebar'

export function SidebarPane() {
  const sidebar = useAppState(state => state.sidebar)
  const sidebarVisible = useAppState(state => state.ui.sidebarVisible)
  return sidebarVisible ? <Sidebar payload={sidebar} /> : null
}
