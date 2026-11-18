import { describe, expect, it } from 'vitest'
import { parseSSE, splitAnswerText } from './App'

describe('splitAnswerText', () => {
  it('turns known citations into citation tokens', () => {
    expect(splitAnswerText('Según [Doc 2] y [Doc 1].')).toEqual([
      { kind: 'text', value: 'Según ' },
      { kind: 'citation', value: '2' },
      { kind: 'text', value: ' y ' },
      { kind: 'citation', value: '1' },
      { kind: 'text', value: '.' },
    ])
  })

  it('leaves unknown citation numbers as plain text', () => {
    expect(splitAnswerText('No existe [Doc 9]', [1, 2])).toEqual([
      { kind: 'text', value: 'No existe [Doc 9]' },
    ])
  })
})

describe('parseSSE', () => {
  it('parses named events with JSON data', async () => {
    const body = 'event: token\ndata: {"text":"hola"}\n\nevent: done\ndata: {"answer_id":1}\n\n'
    const response = new Response(body, { headers: { 'Content-Type': 'text/event-stream' } })
    const events = []
    for await (const event of parseSSE(response)) events.push(event)
    expect(events).toEqual([
      { event: 'token', data: { text: 'hola' } },
      { event: 'done', data: { answer_id: 1 } },
    ])
  })
})
