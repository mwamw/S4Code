import React, { useEffect, useState } from 'react'
import { render, Box, Text } from 'ink'

function App() {
  const [lines, setLines] = useState<string[]>([])

  useEffect(() => {
    const timer = setInterval(() => {
      setLines(prev => [...prev, `Line ${prev.length + 1}`])
    }, 100)
    return () => clearInterval(timer)
  }, [])

  return (
    <Box flexDirection="column" height={10} width={40} borderStyle="round">
      <Box flexDirection="column" overflow="hidden" flexGrow={1} justifyContent="flex-end">
        <Box flexDirection="column">
          {lines.map((line, i) => (
            <Text key={i}>{line}</Text>
          ))}
        </Box>
      </Box>
      <Box borderStyle="single" borderColor="green">
        <Text>Input Bar</Text>
      </Box>
    </Box>
  )
}

render(<App />)
