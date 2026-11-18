import { describe, expect, it } from 'vitest'
import { splitAnswerText } from './App'

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
