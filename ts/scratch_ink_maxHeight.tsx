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

  // Calculate if we need to constrain the height.
  // We want to limit the box height to rows - 3 (for the input bar and padding)
  // Unfortunately Ink Box doesn't support maxHeight, but if we set `height` dynamically 
  // only when we exceed it, maybe it works?
  // Wait, if we set flexGrow={1} and the wrapper has a fixed height, it handles it.
  
  // Let's force a fixed height on the App root container if we want it fullscreen.
  // But we DO NOT want fullscreen if there are few lines.
  // If lines are small, we just let it be. If lines are many, we bound it.
  // The simplest is: we don't know the exact height of the lines.
  // BUT we can just slice the array of lines!

  const maxLines = Math.max(5, rows - 5)
  const visibleLines = lines.length > maxLines ? lines.slice(-maxLines) : lines

  return (
    <Box flexDirection="column" width={40}>
      <Text>-- Static Mock --</Text>
      <Box flexDirection="column" overflow="hidden" justifyContent="flex-end">
        <Box flexDirection="column">
          {visibleLines.map((line, i) => (
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
