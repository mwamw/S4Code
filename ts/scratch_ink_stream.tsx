import React, { useEffect, useState } from 'react'
import { render, Box, Text, Static } from 'ink'

function App() {
  const [staticLines, setStaticLines] = useState<string[]>([])
  const [buffer, setBuffer] = useState<string>('')
  
  useEffect(() => {
    let count = 0;
    const interval = setInterval(() => {
      count++
      if (count > 20) {
        clearInterval(interval)
        return
      }
      setBuffer(prev => prev + `Chunk ${count}... ` + (count % 3 === 0 ? '\n' : ''))
    }, 100)
    return () => clearInterval(interval)
  }, [])

  // Process buffer into static lines
  useEffect(() => {
    if (buffer.includes('\n')) {
      const lines = buffer.split('\n')
      const incomplete = lines.pop() || ''
      setStaticLines(prev => [...prev, ...lines])
      setBuffer(incomplete)
    }
  }, [buffer])

  return (
    <Box flexDirection="column" width="100%">
      <Static items={staticLines}>
        {(line, i) => <Text key={i}>{line}</Text>}
      </Static>
      {/* Live / Dynamic */}
      {buffer && (
        <Box>
          <Text>{buffer}</Text>
        </Box>
      )}
      <Box borderStyle="single" borderColor="green">
        <Text>Input Bar</Text>
      </Box>
    </Box>
  )
}

render(<App />)
