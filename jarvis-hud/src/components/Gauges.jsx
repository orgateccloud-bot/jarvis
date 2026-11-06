// Medidores em SVG: anel de progresso e sparkline. E o número que anda até o valor novo.
import { useEffect, useRef, useState } from 'react'
import { interpolar } from '../lib/contador.js'

const movimentoReduzido = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/**
 * Número que anda até o valor novo. Escreve direto no elemento, sem renderizar o React a cada quadro.
 * `formato` precisa ser estável (função do módulo): trocar de função reinicia a animação.
 */
export function Contador({ valor, formato = String, ms = 600 }) {
  const ref = useRef(null)
  const mostrado = useRef(valor)
  const [inicial] = useState(() => (valor == null ? '—' : formato(valor)))

  useEffect(() => {
    const el = ref.current
    const de = mostrado.current
    if (valor == null || de == null || de === valor || movimentoReduzido()) {
      mostrado.current = valor
      el.textContent = valor == null ? '—' : formato(valor)
      return undefined
    }
    let raf = 0
    let inicio = null
    const passo = agora => {
      inicio ??= agora
      const p = (agora - inicio) / ms
      mostrado.current = interpolar(de, valor, p)
      el.textContent = formato(mostrado.current)
      if (p < 1) raf = requestAnimationFrame(passo)
    }
    raf = requestAnimationFrame(passo)
    return () => cancelAnimationFrame(raf)
  }, [valor, formato, ms])

  return <span ref={ref}>{inicial}</span>
}

/** `faixa`: 0, 1 ou 2 (lib/contador.js). O anel dá um pulso só ao subir de faixa. */
export function Ring({ value = 0, size = 64, stroke = 5, color = 'var(--aurora-2)', faixa = 0, children, label }) {
  const ref = useRef(null)
  const antes = useRef(faixa)
  useEffect(() => {
    if (faixa > antes.current && !movimentoReduzido()) {
      ref.current.animate?.([{ transform: 'scale(1)' }, { transform: 'scale(1.12)' }, { transform: 'scale(1)' }],
        { duration: 700, easing: 'ease-out' })
    }
    antes.current = faixa
  }, [faixa])
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const v = Math.max(0, Math.min(100, value || 0))
  return (
    <div ref={ref} className="ring" style={{ width: size, height: size }} role="meter" aria-valuenow={Math.round(v)}
      aria-valuemin={0} aria-valuemax={100} aria-label={label}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,.07)" strokeWidth={stroke} />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - v / 100)} transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: 'stroke-dashoffset 600ms var(--ease), stroke 300ms', filter: `drop-shadow(0 0 4px ${color})` }}
        />
      </svg>
      <div className="ring-center">{children}</div>
    </div>
  )
}

export function Sparkline({ data = [], color = 'var(--aurora-3)', height = 34, max = 100 }) {
  const w = 120
  if (data.length < 2) return <svg className="spark" viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" />
  const pts = data.map((v, i) => [(i / (data.length - 1)) * w, height - (Math.min(v, max) / max) * (height - 2) - 1])
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const area = `0,${height} ${line} ${w},${height}`
  const id = `g${color.replace(/[^a-z0-9]/gi, '')}`
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.35" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={area} fill={`url(#${id})`} />
      <polyline points={line} fill="none" stroke={color} strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}
