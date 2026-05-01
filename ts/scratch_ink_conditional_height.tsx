import React, { useEffect, useState } from 'react'
import { render, Box, Text, useStdout } from 'ink'

function App() {
  const [lines, setLines] = useState<string[]>([])
  const { stdout } = useStdout()
  const [rows, setRows] = useState(stdout.rows || 24)

  useEffect(() => {
    const onResize = () => setRows(stdout.rows)
    stdout.on('resize', onResize)
    return () => {
      stdout.off('resize', onResize)
    }
  }, [stdout])

  useEffect(() => {
    const timer = setInterval(() => {
      setLines(prev => [...prev, `Line ${prev.length + 1}`])
    }, 50)
    return () => clearInterval(timer)
  }, [])

  const maxLiveHeight = rows - 5
  // Approximate height of lines (ignoring wrapping for now)
  const isOverflowing = lines.length > maxLiveHeight

  return (
    <Box flexDirection="column" width={40}>
      <Text>-- Static Mock --</Text>
      <Box 
        flexDirection="column" 
        overflow="hidden" 
        justifyContent="flex-end"
        height={isOverflowing ? maxLiveHeight : undefined}
      >
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
