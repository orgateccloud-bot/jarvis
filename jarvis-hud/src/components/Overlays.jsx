import { useEffect, useState } from 'react'

const LINES = ['Ignição estelar', 'Desdobrando a galáxia', 'Conectando ao Claude', 'Sistemas online']

/** Textos da sequência de ignição, sincronizados com o boot do cosmos (~3,2 s). */
export function BootIgnition() {
  const [step, setStep] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setStep(s => s + 1), 850)
    return () => clearInterval(id)
  }, [])
  if (step > LINES.length) return null
  return (
    <div className={`boot ${step === LINES.length ? 'boot-out' : ''}`} aria-hidden="true">
      <div className="boot-brand">JARVIS</div>
      <div className="boot-line" key={step}>{LINES[Math.min(step, LINES.length - 1)]}</div>
    </div>
  )
}

export function Toasts({ toasts, onDismiss }) {
  return (
    <div className="toasts" role="status" aria-live="assertive">
      {toasts.map(t => (
        <button key={t.id} className={`toast glass toast-${t.kind}`} onClick={() => onDismiss(t.id)} title="Dispensar">
          {t.text}
        </button>
      ))}
    </div>
  )
}

/**
 * Área clicável sobre o sol: abre/fecha a conversa por voz; enquanto ele fala, interrompe.
 * pos: { cx, cy, rp } em px quando o sol sai da posição padrão do CSS (modo vidro): cobre só o disco,
 * para não roubar o clique dos painéis que encostam na borda.
 */
export function SunButton({ mode, speaking, onClick, disabled, pos }) {
  const label = speaking ? 'Interromper o JARVIS' : mode === 'active' ? 'Encerrar a conversa' : 'Conversar com o JARVIS'
  const style = pos ? { left: pos.cx, top: pos.cy, width: pos.rp * 1.9, height: pos.rp * 1.9 } : undefined
  return (
    <button className={`sun-hit ${mode === 'active' ? 'active' : ''}`} onClick={onClick} disabled={disabled} style={style}
      aria-label={label} title={disabled ? 'Este navegador não tem reconhecimento de voz (use Chrome ou Edge)' : label} />
  )
}

const HINT = {
  off: 'Clique no sol para conversar',
  wake: 'Diga “Jarvis” para começar',
}

/** Legenda sob o sol: o que o usuário está dizendo, ou uma dica do que fazer. pos: como no SunButton. */
export function Caption({ mode, phase, caption, pos }) {
  let text = caption
  if (!text) {
    if (phase === 'listening') text = 'Ouvindo…'
    else if (phase === 'thinking') text = 'Pensando…'
    else if (phase === 'idle') text = HINT[mode] || ''
  }
  if (!text) return null
  return (
    <div className={`caption ${caption ? 'live' : ''}`} aria-live="polite"
      style={pos ? { left: pos.cx, top: pos.cy + pos.rp + 14 } : undefined}>
      {caption ? `“${caption}”` : text}
    </div>
  )
}
