import React, { useEffect, useState } from 'react'
import { render, Box, Text, Static, useStdout } from 'ink'

function App() {
  const [staticLines, setStaticLines] = useState<string[]>([])
  const [liveLines, setLiveLines] = useState<string[]>([])
  const { stdout } = useStdout()

  useEffect(() => {
    let count = 0
    const timer = setInterval(() => {
      count++
      if (count <= 10) {
        setLiveLines(prev => [...prev, `Live Line ${count}`])
      } else {
        // Commit
        setStaticLines(prev => [...prev, `Committed block ${Date.now()}`])
        setLiveLines([])
        count = 0
      }
    }, 200)
    return () => clearInterval(timer)
  }, [])

  return (
    <Box flexDirection="column" minHeight={stdout.rows} width="100%">
      <Static items={staticLines}>
        {(line, i) => <Text key={i}>{line}</Text>}
      </Static>
      
      {/* Dynamic Area */}
      <Box flexDirection="column" flexGrow={1} justifyContent="flex-end" overflow="hidden">
        {liveLines.map((line, i) => (
          <Text key={i}>{line}</Text>
        ))}
      </Box>
      <Box borderStyle="single" borderColor="green">
        <Text>Input Bar</Text>
      </Box>
    </Box>
  )
}

render(<App />)
