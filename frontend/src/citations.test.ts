import { describe, expect, it } from 'vitest'
import { consumeSSE, parseSSE, splitAnswerText } from './App'

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

describe('consumeSSE', () => {
  it('dispatches each named event to its handler', async () => {
    const body = 'event: token\ndata: {"text":"hola"}\n\nevent: done\ndata: {"answer_id":1}\n\n'
    const response = new Response(body, { headers: { 'Content-Type': 'text/event-stream' } })
    const seen: string[] = []
    const completed = await consumeSSE(response, {
      token: (data) => { seen.push(`token:${data.text}`) },
      done: (data) => { seen.push(`done:${data.answer_id}`) },
    })
    expect(completed).toBe(true)
    expect(seen).toEqual(['token:hola', 'done:1'])
  })

  it('reports an interrupted stream instead of throwing', async () => {
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('event: token\ndata: {"text":"ho'))
        controller.error(new Error('conexión cortada'))
      },
    })
    const response = new Response(body, { headers: { 'Content-Type': 'text/event-stream' } })
    const completed = await consumeSSE(response, { token: () => {} })
    expect(completed).toBe(false)
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
