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
