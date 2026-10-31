// SPIKE: um painel de vidro de CPU e RAM, como o do vídeo, com a transição do modo palco.
import { useLayoutEffect, useRef } from 'react'
import { Ring, Sparkline } from '../components/Gauges.jsx'
import { PALCO_ESCALA, SPIKE } from './params.js'
import { alvoSol, painelCPU } from './arranjo.js'

const level = v => (v >= 90 ? 'var(--danger)' : v >= 75 ? 'var(--warn)' : 'var(--aurora-3)')

export default function HoloSpike({ vitals, history, palco, view }) {
  const ref = useRef(null)
  const antes = useRef(palco)
  const { W, H } = view
  const repouso = painelCPU({ sol: alvoSol({ palco: false, W, H, r: SPIKE.sunR, y: SPIKE.sunY }), W, H })
  const noPalco = painelCPU({ sol: alvoSol({ palco: true, W, H, r: SPIKE.sunR, y: SPIKE.sunY }), W, H, escala: PALCO_ESCALA })
  const p = palco ? noPalco : repouso

  // will-change só durante a transição: o bitmap fica fixo enquanto anima e volta a ser rasterizado nítido no fim
  useLayoutEffect(() => {
    const el = ref.current
    if (SPIKE.wc !== 'toggle' || antes.current === palco || !el) return
    antes.current = palco
    el.classList.add('wc')
    const fim = e => { if (e.propertyName === 'transform') el.classList.remove('wc') }
    el.addEventListener('transitionend', fim)
    return () => el.removeEventListener('transitionend', fim)
  }, [palco])

  const cpu = history.cpu.slice(-32)
  const anel = [['CPU', vitals?.cpu_percent], ['RAM', vitals?.ram_percent], ['Disco', vitals?.disk_percent]]
  return (
    <div className="holo-layer">
      <section
        ref={ref}
        className={`holo-panel ${SPIKE.wc === 'always' ? 'wc' : ''}`}
        aria-label="CPU e RAM"
        style={{ width: repouso.w, height: repouso.h, transform: `translate(${p.left}px, ${p.top}px) rotateY(-10deg) scale(${p.escala})` }}
      >
        <header className="holo-head">
          <h2>CPU</h2>
          <span className="holo-tag">{vitals ? `${vitals.uptime_hours?.toFixed(1)} h ligado` : 'aguardando'}</span>
        </header>
        <div className="holo-rings">
          {anel.map(([label, v]) => (
            <div className="holo-ring" key={label}>
              <Ring value={v} size={92} stroke={6} color={level(v ?? 0)} label={label}>
                <span className="mono holo-num">{v == null ? '—' : Math.round(v)}</span>
                <span className="holo-ring-label">{label}</span>
              </Ring>
            </div>
          ))}
        </div>
        <h3 className="holo-sub">RAM</h3>
        <Sparkline data={history.ram} color="#0EA5E9" height={44} />
        <h3 className="holo-sub">CPU · últimos {cpu.length * 3} s</h3>
        <div className="holo-bars" aria-hidden="true">
          {cpu.map((v, i) => <span key={i} style={{ height: `${Math.max(3, Math.min(100, v))}%` }} />)}
        </div>
        <dl className="holo-kv">
          <div><dt>CPU</dt><dd className="mono">{vitals ? `${vitals.cpu_percent?.toFixed(1)}%` : '—'}</dd></div>
          <div><dt>RAM</dt><dd className="mono">{vitals ? `${vitals.ram_percent?.toFixed(1)}%` : '—'}</dd></div>
          <div><dt>Disco</dt><dd className="mono">{vitals ? `${vitals.disk_percent?.toFixed(1)}%` : '—'}</dd></div>
        </dl>
      </section>
    </div>
  )
}
