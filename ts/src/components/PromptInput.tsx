import React from 'react'
import { Box, Text } from 'ink'
import TextInput from 'ink-text-input'

export function PromptInput(props: {
  value: string
  busy: boolean
  onChange: (value: string) => void
  onSubmit: (value: string) => void
}) {
  return (
    <Box flexDirection="column" marginTop={1}>
      <Box>
        <Text color="cyan">{props.busy ? 'running' : '>'}</Text>
        <Text> </Text>
        <TextInput
          value={props.value}
          onChange={props.onChange}
          onSubmit={props.onSubmit}
          placeholder="Ask S4Code or type /help"
        />
      </Box>
    </Box>
  )
}
