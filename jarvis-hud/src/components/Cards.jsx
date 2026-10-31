import { Ring, Sparkline } from './Gauges.jsx'
import { MODEL_TO_TIER, ROUTE_LABEL, ROUTE_TO_TIER, TIERS } from '../lib/tiers.js'

const level = v => (v >= 90 ? 'var(--danger)' : v >= 75 ? 'var(--warn)' : 'var(--aurora-3)')
const usd = v => `US$ ${(v ?? 0).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const pct = v => `${(v ?? 0).toLocaleString('pt-BR', { maximumFractionDigits: 1 })}%`

export function Card({ title, aside, children, className = '' }) {
  return (
    <section className={`card glass ${className}`}>
      <header className="card-head">
        <h2>{title}</h2>
        {aside}
      </header>
      {children}
    </section>
  )
}

export function VitalsCard({ vitals, history }) {
  const items = [
    ['CPU', vitals?.cpu_percent],
    ['RAM', vitals?.ram_percent],
    ['Disco', vitals?.disk_percent],
  ]
  return (
    <Card title="Sistema" aside={vitals && <span className="muted mono">{vitals.uptime_hours?.toFixed(1)} h ligado</span>}>
      <div className="vitals">
        {items.map(([label, v]) => (
          <div className="vital" key={label}>
            <Ring value={v} size={58} color={level(v ?? 0)} label={label}>
              <span className="mono ring-num">{v == null ? '—' : Math.round(v)}</span>
            </Ring>
            <span className="vital-label">{label}</span>
          </div>
        ))}
      </div>
      <div className="spark-row">
        <span className="muted">CPU</span><Sparkline data={history.cpu} color="#4D7CFF" />
      </div>
      <div className="spark-row">
        <span className="muted">RAM</span><Sparkline data={history.ram} color="#0EA5E9" />
      </div>
    </Card>
  )
}

export function CostCard({ costs }) {
  const pct = costs?.uso_pct ?? 0
  const color = costs?.estado === 'teto' ? 'var(--danger)' : costs?.estado === 'economia' ? 'var(--warn)' : 'var(--aurora-2)'
  const estado = { normal: 'Normal', economia: 'Economia', teto: 'Teto atingido' }[costs?.estado] || '—'
  return (
    <Card title="Custo Claude" aside={<span className={`badge badge-${costs?.estado || 'normal'}`}>{estado}</span>}>
      <div className="cost">
        <Ring value={pct} size={92} stroke={6} color={color} label="Uso do teto mensal">
          <span className="mono ring-big">{Math.round(pct)}%</span>
          <span className="ring-sub">do teto</span>
        </Ring>
        <dl className="kv">
          <div><dt>Mês</dt><dd className="mono">{usd(costs?.mes_usd)}</dd></div>
          <div><dt>Teto</dt><dd className="mono">{usd(costs?.teto_usd)}</dd></div>
          <div><dt>Hoje</dt><dd className="mono">{usd(costs?.hoje_usd)}</dd></div>
          <div><dt>Cache</dt><dd className="mono">{costs ? `${costs.cache_hit_pct}%` : '—'}</dd></div>
        </dl>
      </div>
      <p className="muted small">{costs ? `${costs.turnos_claude_mes} turnos com o Claude neste mês` : 'Aguardando o núcleo…'}</p>
      <Telemetria t={costs?.telemetria} teto={costs?.teto_usd} />
    </Card>
  )
}

// Custo do mês por modelo, projeção para o fim do mês e a fatia real do Fable contra a meta.
function Telemetria({ t, teto }) {
  if (!t?.por_modelo?.length) return null
  const passa = teto && t.projecao_mes_usd > teto
  const fable = t.fable
  return (
    <div className="tele" aria-label="Telemetria de custos por modelo">
      <ul className="tele-modelos">
        {t.por_modelo.map(m => {
          const tier = TIERS[MODEL_TO_TIER[m.modelo]]
          return (
            <li key={m.modelo} title={`${m.requisicoes} chamadas · média ${usd(m.media_usd)} por chamada`}>
              <span className="tele-nome">{tier?.label || m.modelo}</span>
              <span className="tele-barra" aria-hidden="true">
                <span style={{ width: `${m.fatia_custo_pct}%`, background: tier?.ui || 'var(--aurora-2)' }} />
              </span>
              <span className="mono tele-valor">{usd(m.custo_usd)}</span>
              <span className="mono tele-pct">{pct(m.fatia_custo_pct)}</span>
            </li>
          )
        })}
      </ul>
      <dl className="kv">
        <div>
          <dt>Projeção do mês</dt>
          <dd className="mono" style={passa ? { color: 'var(--warn)' } : undefined}>{usd(t.projecao_mes_usd)}</dd>
        </div>
        <div title={`Fatia real das chamadas que foram ao Fable; meta: ${fable.meta_pct}%`}>
          <dt>Fable · meta {pct(fable.meta_pct)}</dt>
          <dd className="mono">{pct(fable.fatia_req_pct)} das chamadas</dd>
        </div>
      </dl>
    </div>
  )
}

export function NeuralCard({ neural }) {
  const tierKey = ROUTE_TO_TIER[neural?.rota] || 'regras'
  const t = TIERS[tierKey]
  const uso = neural?.uso
  return (
    <Card title="Neural" className="neural" aside={neural && <span className="chip" style={{ '--chip': t.ui }}>{t.label}</span>}>
      {neural ? (
        <>
          <dl className="kv kv-wide">
            <div><dt>Camada</dt><dd>{ROUTE_LABEL[neural.rota] || '—'}</dd></div>
            <div><dt>Modelo</dt><dd className="mono">{uso?.modelo || neural.modelo}</dd></div>
            <div><dt>Estrela</dt><dd>{t.classe} · <span className="mono">{t.temp.toLocaleString('pt-BR')} K</span></dd></div>
            {neural.effort && <div><dt>Esforço</dt><dd className="mono">{neural.effort}</dd></div>}
          </dl>
          <div className="thought" aria-label="Pensamento do modelo">
            <span className="thought-label">pensamento</span>
            <p>{neural.thinking ? neural.thinking.slice(-360) : <span className="muted">{neural.motivo}</span>}</p>
          </div>
          {uso && (
            <div className="turn mono">
              <span>US$ {(uso.custo_usd ?? 0).toFixed(4).replace('.', ',')}</span>
              <span>{uso.entrada}↑ {uso.saida}↓</span>
              <span>cache {uso.cache_read}</span>
              <span title={uso.audit_hash}>#{uso.audit_hash?.slice(0, 8)}</span>
            </div>
          )}
        </>
      ) : (
        <p className="muted">Nenhum turno ainda. A camada, o modelo e o pensamento aparecem aqui em tempo real.</p>
      )}
    </Card>
  )
}
