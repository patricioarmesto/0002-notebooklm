import { useCallback, useEffect, useRef, useState } from 'react'

const API = ((import.meta as any).env?.VITE_API_URL as string) || 'http://localhost:8000'

export type Doc = { id: number; title: string; filename: string; source_type: string; chunk_count: number }
export type Citation = { n: number; doc_id: number; chunk_id: string; doc_title: string; page: number; chunk_index: number }
export type Chunk = { text: string; doc_title: string; doc_id: number; page: number; chunk_index: number }
type Token = { kind: 'text' | 'citation'; value: string }

export function splitAnswerText(text: string, known: number[] = []): Token[] {
  const result: Token[] = []
  const regex = /\[Doc (\d+)\]/g
  let last = 0
  let match: RegExpExecArray | null
  while ((match = regex.exec(text)) !== null) {
    const number = Number(match[1])
    if (known.length > 0 && !known.includes(number)) continue
    if (match.index > last) result.push({ kind: 'text', value: text.slice(last, match.index) })
    result.push({ kind: 'citation', value: match[1] })
    last = match.index + match[0].length
  }
  if (last < text.length) result.push({ kind: 'text', value: text.slice(last) })
  return result
}

export async function* parseSSE(response: Response): AsyncGenerator<{ event: string; data: any }> {
  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let index: number
    while ((index = buffer.indexOf('\n\n')) >= 0) {
      const raw = buffer.slice(0, index)
      buffer = buffer.slice(index + 2)
      let event = 'message'
      const dataLines: string[] = []
      for (const line of raw.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
      }
      if (dataLines.length) yield { event, data: JSON.parse(dataLines.join('\n')) }
    }
  }
}

export default function App() {
  const [docs, setDocs] = useState<Doc[]>([])
  const [ready, setReady] = useState(false)
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [citations, setCitations] = useState<Citation[]>([])
  const [activeChunk, setActiveChunk] = useState<Chunk | null>(null)
  const [uploadProgress, setUploadProgress] = useState<{ processed: number; total: number } | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const loadDocs = useCallback(async () => {
    const response = await fetch(`${API}/api/documents`)
    if (response.ok) setDocs(await response.json())
  }, [])

  useEffect(() => {
    let alive = true
    const check = async () => {
      try {
        const response = await fetch(`${API}/api/ready`)
        if (alive && response.ok) {
          setReady(true)
          await loadDocs()
        }
      } catch {}
    }
    void check()
    const timer = setInterval(check, 3000)
    return () => { alive = false; clearInterval(timer) }
  }, [loadDocs])

  const onUpload = async (file: File) => {
    setError('')
    setUploadProgress({ processed: 0, total: 0 })
    try {
      const form = new FormData()
      form.append('file', file)
      const response = await fetch(`${API}/api/upload`, { method: 'POST', body: form })
      if (!response.ok) { setError('No se pudo subir el documento'); return }
      for await (const event of parseSSE(response)) {
        if (event.event === 'progress') setUploadProgress({ processed: event.data.processed, total: event.data.total })
        if (event.event === 'error') setError(event.data.message)
        if (event.event === 'done') await loadDocs()
      }
    } catch {
      setError('Se perdió la conexión durante la indexación')
    } finally {
      setUploadProgress(null)
    }
  }

  const onAsk = async () => {
    if (!question.trim()) return
    setAnswer(''); setCitations([]); setError(''); setLoading(true)
    try {
      const response = await fetch(`${API}/api/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      })
      if (!response.ok) { setError('No se pudo hacer la pregunta'); return }
      for await (const event of parseSSE(response)) {
        if (event.event === 'citations') setCitations(event.data.citations)
        if (event.event === 'token') setAnswer((previous) => previous + event.data.text)
        if (event.event === 'error') setError(event.data.message)
        if (event.event === 'done') setAnswer(event.data.text)
      }
    } catch {
      setError('Se perdió la conexión durante la respuesta')
    } finally {
      setLoading(false)
    }
  }

  const openCitation = async (n: string) => {
    const citation = citations.find((c) => String(c.n) === n)
    if (!citation) return
    const response = await fetch(`${API}/api/chunks/${citation.chunk_id}`)
    if (response.ok) setActiveChunk(await response.json())
  }

  const knownNumbers = citations.map((c) => c.n)
  const tokens = splitAnswerText(answer, knownNumbers.length ? knownNumbers : [])

  return (
    <div className="flex h-screen bg-slate-50 text-slate-900">
      <aside className="w-80 shrink-0 border-r border-slate-200 bg-white p-5">
        <h1 className="text-lg font-bold">NotebookLM local</h1>
        <p className="mt-1 text-xs text-slate-500">Solo responde con tus documentos</p>
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.txt"
          className="hidden"
          onChange={(event) => { const file = event.target.files?.[0]; if (file) void onUpload(file) }}
        />
        <button
          onClick={() => fileRef.current?.click()}
          className="mt-5 w-full rounded bg-indigo-600 px-3 py-2 text-sm font-semibold text-white hover:bg-indigo-700"
        >
          Subir PDF/TXT
        </button>
        {uploadProgress && (
          <div className="mt-3">
            <div className="h-2 w-full overflow-hidden rounded bg-slate-200">
              <div
                className="h-full bg-indigo-500 transition-all"
                style={{ width: uploadProgress.total ? `${(uploadProgress.processed / uploadProgress.total) * 100}%` : '10%' }}
              />
            </div>
            <p className="mt-1 text-xs text-slate-500">Indexando {uploadProgress.processed}/{uploadProgress.total} chunks</p>
          </div>
        )}
        <h2 className="mt-7 text-xs font-bold uppercase tracking-wide text-slate-500">Documentos</h2>
        {!ready && <p className="mt-3 text-sm text-slate-500">Inicializando…</p>}
        {ready && docs.length === 0 && <p className="mt-3 text-sm text-slate-500">Subí un documento para empezar</p>}
        <ul className="mt-2 space-y-2">
          {docs.map((doc) => (
            <li key={doc.id} className="rounded border border-slate-200 px-3 py-2 text-sm">
              <p className="font-medium">[Doc {doc.id}] {doc.title}</p>
              <p className="text-xs text-slate-500">{doc.chunk_count} chunks · {doc.source_type}</p>
            </li>
          ))}
        </ul>
      </aside>

      <main className="flex flex-1 flex-col p-8">
        <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col">
          <h2 className="text-2xl font-bold">Preguntá sobre tus documentos</h2>
          {error && <p className="mt-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
          <div className="mt-6 flex gap-2">
            <input
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => { if (event.key === 'Enter') void onAsk() }}
              placeholder="¿Qué dice Bitly sobre los clics?"
              className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
            />
            <button onClick={() => void onAsk()} disabled={loading} className="rounded bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
              Preguntar
            </button>
          </div>
          <div className="mt-6 min-h-52 rounded border border-slate-200 bg-white p-5 text-sm leading-7">
            {answer ? (
              <p className="whitespace-pre-wrap">
                {tokens.map((token, index) => token.kind === 'text'
                  ? <span key={index}>{token.value}</span>
                  : <button
                      key={index}
                      onClick={() => void openCitation(token.value)}
                      className="mx-0.5 rounded bg-indigo-100 px-1 font-semibold text-indigo-700 hover:bg-indigo-200"
                    >[Doc {token.value}]</button>)}
              </p>
            ) : (
              <p className="text-slate-400">{loading ? 'Pensando…' : 'La respuesta aparecerá acá, con citas clicables.'}</p>
            )}
          </div>
        </div>
      </main>

      {activeChunk && (
        <div className="fixed inset-0 flex items-center justify-center bg-black/40 p-6" onClick={() => setActiveChunk(null)}>
          <div className="max-w-xl rounded bg-white p-6 shadow-xl" onClick={(event) => event.stopPropagation()}>
            <p className="text-xs font-bold uppercase text-indigo-600">{activeChunk.doc_title} · pág. {activeChunk.page} · chunk {activeChunk.chunk_index}</p>
            <h3 className="mt-1 text-lg font-bold">{activeChunk.doc_title}</h3>
            <p className="mt-4 whitespace-pre-wrap text-sm leading-7">{activeChunk.text}</p>
            <button onClick={() => setActiveChunk(null)} className="mt-5 rounded border px-3 py-1 text-sm">Cerrar</button>
          </div>
        </div>
      )}
    </div>
  )
}
