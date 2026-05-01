import React, { createContext, useContext } from 'react'

type Theme = {
  accent: string
  muted: string
  border: string
}

const defaultTheme: Theme = {
  accent: 'cyan',
  muted: 'gray',
  border: 'blue',
}

const ThemeContext = createContext<Theme>(defaultTheme)

export function ThemeProvider(props: { children: React.ReactNode }) {
  return (
    <ThemeContext.Provider value={defaultTheme}>
      {props.children}
    </ThemeContext.Provider>
  )
}

export function useTheme(): Theme {
  return useContext(ThemeContext)
}
