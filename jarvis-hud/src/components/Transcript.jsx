import { useEffect, useRef } from 'react'
import Markdown from '../lib/Markdown.jsx'
import SafeBoundary from './SafeBoundary.jsx'
import { TIERS } from '../lib/tiers.js'

const VISIBLE = 10

export default function Transcript({ messages }) {
  const endRef = useRef(null)
  const last = messages[messages.length - 1]
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length, last?.text])

  if (!messages.length) return null
  return (
    <ol className="transcript" aria-live="polite" aria-label="Conversa">
      {messages.slice(-VISIBLE).map(m => {
        const t = TIERS[m.tier] || TIERS.regras
        return (
          <li key={m.id} className={`msg msg-${m.role}`} style={m.role === 'jarvis' ? { '--msg': t.ui } : undefined}>
            {m.role === 'jarvis' && (
              <span className="msg-meta">
                <span className="msg-dot" aria-hidden="true" />
                {m.tier ? t.label : 'JARVIS'}
                {m.custo != null && <span className="mono"> · US$ {m.custo.toFixed(4).replace('.', ',')}</span>}
              </span>
            )}
            <div className="msg-body">
              {m.role === 'jarvis'
                ? (m.text
                    ? <SafeBoundary fallback={<p className="md">{m.text}</p>} resetKey={m.text}><Markdown text={m.text} /></SafeBoundary>
                    : <span className="typing" aria-label="pensando"><i /><i /><i /></span>)
                : <>{m.mode && <span className="msg-mode">{m.mode}</span>}{m.text}</>}
              {m.streaming && m.text && <span className="caret" aria-hidden="true" />}
            </div>
          </li>
        )
      })}
      <li ref={endRef} aria-hidden="true" className="msg-end" />
    </ol>
  )
}
