import { useEffect, useRef, useState } from 'react'
import Markdown from '../lib/Markdown.jsx'
import SafeBoundary from './SafeBoundary.jsx'
import { TIERS } from '../lib/tiers.js'

const VISIBLE = 12

// 1536 → "1,5 KB"; 3,2 GB → "3,2 GB"
function tamanho(bytes) {
  const u = ['bytes', 'KB', 'MB', 'GB', 'TB']
  let v = bytes || 0
  let i = 0
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++ }
  return `${i ? v.toFixed(1).replace('.', ',') : v} ${u[i]}`
}

const STATUS = {
  aprovando: 'Aprovando…', negando: 'Negando…', aprovado: 'Aprovado ✓', negado: 'Negado', expirado: 'Expirou — negado',
}

function ApprovalCard({ m, onDecide }) {
  const [now, setNow] = useState(() => Date.now())
  const pendente = m.status === 'pendente'
  useEffect(() => {
    if (!pendente) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [pendente])
  const restante = Math.max(0, Math.ceil((m.expiraEm - now) / 1000))
  return (
    <div className={`approval approval-${m.status}`} role="group" aria-label="Confirmação de ação">
      <div className="approval-head">
        <span className="approval-icon" aria-hidden="true">⚡</span>
        <span>Posso <strong>{m.resumo}</strong>?</span>
      </div>
      {m.detalhes?.itens?.length > 0 && (
        <div className="approval-lote">
          <ul>{m.detalhes.itens.map((n, i) => <li key={i}>{n}</li>)}</ul>
          <span className="mono">
            {m.detalhes.outros > 0 && `e mais ${m.detalhes.outros} · `}
            {tamanho(m.detalhes.total_bytes ?? m.detalhes.total_gb * 2 ** 30)} no total
          </span>
        </div>
      )}
      {m.detalhes?.comando && (
        <div className="approval-lote">
          <code className="approval-cmd mono">{m.detalhes.comando}</code>
          {m.detalhes.efeito && <p className="approval-efeito">{m.detalhes.efeito}</p>}
        </div>
      )}
      {pendente ? (
        <div className="approval-actions">
          <button className="btn-yes" onClick={() => onDecide(m.approvalId, true)}>Aprovar</button>
          <button className="btn-no" onClick={() => onDecide(m.approvalId, false)}>Negar</button>
          <span className="approval-timer mono" aria-label={`${restante} segundos`}>{restante}s · ou diga “sim” / “não”</span>
        </div>
      ) : (
        <div className="approval-status">{STATUS[m.status] || m.status}</div>
      )}
    </div>
  )
}

function ToolChips({ tools }) {
  if (!tools?.length) return null
  return (
    <div className="tools" aria-label="Ferramentas usadas">
      {tools.map((t, i) => (
        <span key={i} className={`tool ${t.fase === 'inicio' ? 'run' : t.ok ? 'ok' : 'fail'}`} title={t.resumo}>
          {t.fase === 'inicio' ? '⟳' : t.ok ? '✓' : t.negado ? '⦸' : '!'} {t.resumo}
        </span>
      ))}
    </div>
  )
}

export default function Transcript({ messages, onDecide }) {
  const endRef = useRef(null)
  const last = messages[messages.length - 1]
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length, last?.text, last?.status])

  // bolhas do JARVIS vazias (ex.: o modelo só chamou uma ferramenta) não aparecem
  const visible = messages.filter(m => !(m.role === 'jarvis' && !m.text && !m.streaming && !m.tools?.length))
  if (!visible.length) return null
  return (
    <ol className="transcript" aria-live="polite" aria-label="Conversa">
      {visible.slice(-VISIBLE).map(m => {
        if (m.role === 'approval') {
          return <li key={m.id} className="msg msg-approval"><ApprovalCard m={m} onDecide={onDecide} /></li>
        }
        const t = TIERS[m.tier] || TIERS.regras
        const aviso = m.kind === 'aviso' || m.kind === 'saudacao'
        return (
          <li key={m.id} className={`msg msg-${m.role} ${aviso ? `msg-aviso nivel-${m.nivel}` : ''}`}
            style={m.role === 'jarvis' ? { '--msg': t.ui } : undefined}>
            {m.role === 'jarvis' && (
              <span className="msg-meta">
                <span className="msg-dot" aria-hidden="true" />
                {aviso ? (m.titulo || 'Aviso') : m.tier ? t.label : 'JARVIS'}
                {m.custo != null && <span className="mono"> · US$ {m.custo.toFixed(4).replace('.', ',')}</span>}
              </span>
            )}
            {m.role === 'jarvis' && <ToolChips tools={m.tools} />}
            <div className="msg-body">
              {m.role === 'jarvis'
                ? (m.text
                    ? <SafeBoundary fallback={<p className="md">{m.text}</p>} resetKey={m.text}><Markdown text={m.text} /></SafeBoundary>
                    : m.streaming && <span className="typing" aria-label="pensando"><i /><i /><i /></span>)
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
