import { useEffect, useRef, useState } from 'react'
import { TIERS } from '../lib/tiers.js'

const MODES = [
  { key: 'auto', label: 'Auto', hint: 'O JARVIS escolhe o modelo pela complexidade' },
  { key: 'haiku', label: 'Haiku', tier: 'simples', hint: 'Rápido e econômico' },
  { key: 'sonnet', label: 'Sonnet', tier: 'media', hint: 'Equilíbrio' },
  { key: 'opus', label: 'Opus', tier: 'complexa', hint: 'Raciocínio profundo' },
]

const SUGGESTIONS = ['Briefing do dia', 'O que está ocupando espaço no C:?', 'Quais processos estão pesando?',
  'Me lembra de beber água em 30 minutos']

export default function CommandDock({ onSend, busy, mode, onMode, convMode, onToggleConversation, voiceSupported, showSuggestions }) {
  const [text, setText] = useState('')
  const inputRef = useRef(null)
  const listening = convMode === 'active'

  // Ctrl/⌘ + K foca o comando
  useEffect(() => {
    const onKey = e => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        inputRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const submit = e => {
    e.preventDefault()
    if (!text.trim() || busy) return
    onSend(text)
    setText('')
  }

  return (
    <div className="dock-wrap">
      {showSuggestions && (
        <div className="suggestions" role="list">
          {SUGGESTIONS.map(s => (
            <button key={s} role="listitem" className="suggestion glass" disabled={busy} onClick={() => onSend(s)}>{s}</button>
          ))}
        </div>
      )}
      <form className={`dock glass ${busy ? 'is-busy' : ''} ${listening ? 'is-listening' : ''}`} onSubmit={submit}>
        <div className="modes" role="radiogroup" aria-label="Modelo">
          {MODES.map(m => (
            <button key={m.key} type="button" role="radio" aria-checked={mode === m.key} title={m.hint}
              aria-label={`${m.label}: ${m.hint}`}
              className={`mode ${mode === m.key ? 'on' : ''}`} onClick={() => onMode(m.key)}
              style={m.tier ? { '--mode': TIERS[m.tier].ui } : undefined}>
              {m.label}
            </button>
          ))}
        </div>
        <input
          ref={inputRef}
          className="dock-input"
          value={text}
          onChange={e => setText(e.target.value)}
          placeholder={listening ? 'Conversa aberta — fale ou digite…' : 'Digite ou clique no sol para conversar…  (Ctrl+K)'}
          aria-label="Comando para o JARVIS"
          autoFocus
        />
        {voiceSupported && (
          <button type="button" className={`mic ${listening ? 'on' : ''}`} onClick={onToggleConversation}
            aria-pressed={listening} title={listening ? 'Encerrar a conversa por voz' : 'Conversar por voz (mãos livres)'}>
            {listening
              ? <span className="wave" aria-hidden="true"><i /><i /><i /><i /></span>
              : <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
                  <rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
                </svg>}
          </button>
        )}
        <button type="submit" className="send" disabled={busy || !text.trim()} title="Enviar">
          {busy
            ? <span className="spinner" aria-label="enviando" />
            : <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>}
        </button>
      </form>
    </div>
  )
}
