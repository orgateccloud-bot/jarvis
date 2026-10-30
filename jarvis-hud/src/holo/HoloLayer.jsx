// Painéis de vidro em volta do sol (telas largas), como no vídeo de referência: CPU e RAM, custo, modelos,
// neural, último turno e um painel decorativo. O conteúdo vem dos mesmos dados dos cards planos.
// Com o palco aberto, a câmera recua: os painéis dão lugar a blocos compactos ao lado do sol, o palco
// 3D ocupa o centro e os detalhes ficam à direita.
import { Suspense, lazy, memo, useEffect, useRef, useState } from 'react'
import HoloPanel from './HoloPanel.jsx'
import { Blocos, Detalhes, Trilho } from './PalcoUI.jsx'
import { arranjoPalco, arranjoRepouso, trilho } from './arranjo.js'
import projetos from './conteudo/projetos.json'
import SafeBoundary from '../components/SafeBoundary.jsx'
import { TRANSICAO_MS } from '../cosmos/sol.js'
import { CostBadge, CostBody, NeuralBody, NeuralChip, TurnLine } from '../components/Cards.jsx'
import { Ring, Sparkline } from '../components/Gauges.jsx'
import { MODEL_TO_TIER, ROUTE_LABEL, ROUTE_TO_TIER, TIERS } from '../lib/tiers.js'

const carregarPalco = () => import('./PalcoCena.jsx')
const PalcoCena = lazy(carregarPalco)
const DADOS = { projetos }

const level = v => (v >= 90 ? 'var(--danger)' : v >= 75 ? 'var(--warn)' : 'var(--aurora-3)')
const ORDEM = ['regras', 'simples', 'media', 'complexa', 'fable']
const MODO_TIER = { haiku: 'simples', sonnet: 'media', opus: 'complexa', fable: 'fable' }

const Vitais = memo(function Vitais({ vitals, history, w }) {
  const ring = Math.round(Math.max(64, Math.min(96, (w - 90) / 3.6)))
  const itens = [['CPU', vitals?.cpu_percent], ['RAM', vitals?.ram_percent], ['Disco', vitals?.disk_percent]]
  const cpu = history.cpu.slice(-32)
  return (
    <>
      <div className="holo-rings">
        {itens.map(([label, v]) => (
          <Ring key={label} value={v} size={ring} stroke={6} color={level(v ?? 0)} label={label}>
            <span className="mono holo-num">{v == null ? '—' : Math.round(v)}</span>
            <span className="holo-ring-label">{label}</span>
          </Ring>
        ))}
      </div>
      <h3 className="holo-sub">RAM</h3>
      <Sparkline data={history.ram} color="#0EA5E9" height={40} />
      <h3 className="holo-sub">CPU · últimos {cpu.length * 3} s</h3>
      <div className="holo-bars" aria-hidden="true">
        {cpu.map((v, i) => <span key={i} style={{ height: `${Math.max(3, Math.min(100, v))}%` }} />)}
      </div>
    </>
  )
})

const Custo = memo(function Custo({ costs, w }) {
  return <CostBody costs={costs} ring={w < 330 ? 76 : 92} />
})

const Modelos = memo(function Modelos({ rota, mode }) {
  const ativo = ROUTE_TO_TIER[rota] || null
  const fixo = MODO_TIER[mode] || null
  return (
    <>
      {/* a lista remonta a cada rota nova: as linhas entram em sequência, como a lista do vídeo se expandindo */}
      <ul className="holo-list" key={rota || 'nenhuma'}>
        {ORDEM.map((k, n) => {
          const t = TIERS[k]
          return (
            <li key={k} className={k === ativo ? 'on' : ''} style={{ '--c': t.ui, '--k': n }} aria-current={k === ativo ? 'true' : undefined}>
              <span className="holo-li-nome">{t.label}</span>
              {k === fixo && <span className="holo-li-fixo">fixo no dock</span>}
              <span className="holo-li-m mono">{k === 'regras' ? 'local' : t.model.replace('claude-', '')}</span>
            </li>
          )
        })}
      </ul>
      <p className="holo-nota">{ativo ? `Última camada: ${ROUTE_LABEL[rota]}` : 'Nenhum turno ainda'}</p>
    </>
  )
})

const Deco = memo(function Deco({ ram }) {
  const pts = ram.slice(-24)
  const linha = pts.map((v, i) => `${(i / Math.max(1, pts.length - 1)) * 100},${100 - v}`).join(' ')
  return (
    <svg className="holo-deco-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
      {[20, 40, 60, 80].map(y => <line key={y} x1="0" x2="100" y1={y} y2={y} />)}
      {pts.length > 1 && <polyline points={linha} />}
    </svg>
  )
})

export default function HoloLayer({ view, sol, vitals, history, costs, neural, mode, respostas, palco, onPalco }) {
  const a = arranjoRepouso({ W: view.W, H: view.H, sol })
  const ap = arranjoPalco({ W: view.W, H: view.H, sol })
  const [turnoOculto, setTurnoOculto] = useState(null)
  // categoria em cena: fica montada até o fim do fade de saída, para o holograma se dissolver
  const [exibida, setExibida] = useState(palco.categoria)
  if (palco.aberto && palco.categoria !== exibida) setExibida(palco.categoria)
  // a cena só é descartada depois que o sol termina de voltar (o descarte no meio da transição engasga)
  const aberto = useRef(palco.aberto)
  useEffect(() => { aberto.current = palco.aberto })
  const fimSaida = e => {
    if (e.target !== e.currentTarget || e.propertyName !== 'opacity' || palco.aberto) return
    setTimeout(() => { if (!aberto.current) setExibida(null) }, Math.max(0, TRANSICAO_MS - 420) + 40)
  }
  // o código do palco (three) é baixado e compilado no ócio, antes da primeira abertura
  useEffect(() => {
    const ocioso = window.requestIdleCallback || (f => setTimeout(f, 2000))
    const cancelar = window.cancelIdleCallback || clearTimeout
    const id = ocioso(() => { carregarPalco() }, { timeout: 10000 })
    return () => cancelar(id)
  }, [])
  const uso = neural?.uso
  const hash = uso?.audit_hash
  const turnoTier = TIERS[MODEL_TO_TIER[uso?.modelo]]
  const pulso = respostas ? `r${respostas}` : ''
  return (
    <div className="holo-layer">
      <div className={`holo-grupo ${palco.aberto ? 'oculto' : ''}`} aria-hidden={palco.aberto || undefined}>
      <HoloPanel id="deco" rect={a.deco} i={0} decorativo><Deco ram={history.ram} /></HoloPanel>
      <HoloPanel id="cpu" rect={a.cpu} i={1} title="CPU" label="CPU, memória e disco" glare={pulso}
        aside={<span className="holo-tag">{vitals ? `${vitals.uptime_hours?.toFixed(1)} h ligado` : 'aguardando'}</span>}>
        <Vitais vitals={vitals} history={history} w={a.cpu.w} />
      </HoloPanel>
      <HoloPanel id="custo" rect={a.custo} i={2} title="Custo Claude" aside={<CostBadge costs={costs} />} glare={pulso}>
        <Custo costs={costs} w={a.custo.w} />
      </HoloPanel>
      <HoloPanel id="modelos" rect={a.modelos} i={3} title="Modelos" glare={neural?.rota ? `m${neural.rota}${respostas}` : ''}>
        <Modelos rota={neural?.rota} mode={mode} />
      </HoloPanel>
      <HoloPanel id="neural" rect={a.neural} i={4} title="Neural" aside={<NeuralChip neural={neural} />}>
        <NeuralBody neural={neural} semTurno />
      </HoloPanel>
      {hash !== turnoOculto && (
        <HoloPanel id="turno" rect={a.turno} i={5} title={uso ? turnoTier?.label || uso.modelo : 'Último turno'} label="Último turno"
          glare={hash ? `t${hash}` : ''}
          aside={uso && <button className="holo-x" onClick={() => setTurnoOculto(hash)} aria-label="Ocultar o último turno" title="Ocultar">×</button>}>
          {uso ? <TurnLine uso={uso} /> : <p className="muted small">Custo, tokens e hash de auditoria aparecem aqui ao fim de cada resposta.</p>}
        </HoloPanel>
      )}
      </div>

      <div className={`holo-grupo holo-grupo-palco ${palco.aberto ? '' : 'oculto'}`} onTransitionEnd={fimSaida}
        aria-hidden={!palco.aberto || undefined}>
        {/* blocos e detalhes ficam montados (ocultos): abrir o palco só troca a classe, sem montar nada pesado */}
        <Blocos ap={ap} vitals={vitals} costs={costs} neural={neural} />
        <Detalhes rect={ap.detalhes} dados={DADOS[exibida || 'projetos']} selecionado={palco.selecionado} />
        <section className="holo-palco" aria-label="Palco holográfico"
          style={{ width: ap.palco.w, height: ap.palco.h, transform: `translate(${ap.palco.x}px, ${ap.palco.y}px)` }}>
          {exibida && (
            <SafeBoundary resetKey={exibida} fallback={<p className="holo-carregando">O holograma não pôde ser desenhado.</p>}>
              <Suspense fallback={<p className="holo-carregando">Carregando o holograma…</p>}>
                <PalcoCena categoria={exibida} dados={DADOS[exibida]} w={ap.palco.w} h={ap.palco.h}
                  aberto={palco.aberto} selecionado={palco.selecionado}
                  onSelecionar={id => onPalco({ type: 'selecionar', id })} />
              </Suspense>
            </SafeBoundary>
          )}
        </section>
      </div>

      <Trilho rect={trilho({ W: view.W, palco: palco.aberto ? ap.palco : null })} palco={palco} onPalco={onPalco} />
    </div>
  )
}
