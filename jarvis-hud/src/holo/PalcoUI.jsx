// Partes do palco que não dependem do three (ficam no bundle principal): trilho de categorias,
// blocos compactos ao lado do sol no modo palco e painel de detalhes do item selecionado.
import { memo } from 'react'
import HoloPanel from './HoloPanel.jsx'
import { CATEGORIAS } from './palco.js'
import { Ring } from '../components/Gauges.jsx'
import { ROUTE_TO_TIER, TIERS } from '../lib/tiers.js'

const level = v => (v >= 90 ? 'var(--danger)' : v >= 75 ? 'var(--warn)' : 'var(--aurora-3)')
const usd = v => `US$ ${(v ?? 0).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const data = d => new Date(`${d}T12:00:00`).toLocaleDateString('pt-BR')

export function Trilho({ rect, palco, onPalco }) {
  return (
    <nav className={`holo-trilho ${palco.aberto ? 'on' : ''}`} aria-label="Palco holográfico"
      style={{ width: rect.w, transform: `translate(${rect.x}px, ${rect.y}px)` }}>
      {CATEGORIAS.map(c => {
        const ativa = palco.aberto && palco.categoria === c.id
        return (
          <button key={c.id} className={ativa ? 'ativa' : ''} aria-pressed={ativa}
            title={ativa ? 'Fechar o palco' : `Mostrar ${c.fala} no palco`}
            onClick={() => onPalco(ativa ? { type: 'fechar' } : { type: 'abrir', categoria: c.id })}>
            <span className="holo-trilho-ico" aria-hidden="true">◈</span>{c.nome}
          </button>
        )
      })}
      {palco.aberto && (
        <button className="holo-x" onClick={() => onPalco({ type: 'fechar' })} aria-label="Fechar o palco" title="Fechar (Esc)">×</button>
      )}
    </nav>
  )
}

/** Blocos compactos do modo palco: escala 1 e texto de pelo menos 12 px. */
export const Blocos = memo(function Blocos({ ap, vitals, costs, neural }) {
  const tier = TIERS[ROUTE_TO_TIER[neural?.rota] || 'regras']
  const uso = neural?.uso
  const anel = [['CPU', vitals?.cpu_percent], ['RAM', vitals?.ram_percent], ['Disco', vitals?.disk_percent]]
  return (
    <>
      <HoloPanel id="bloco bloco-cpu" rect={ap.cpu} i={0} label="Sistema">
        <span className="bloco-rot">Sistema</span>
        <div className="bloco-aneis">
          {anel.map(([l, v]) => (
            <Ring key={l} value={v} size={48} stroke={4} color={level(v ?? 0)} label={l}>
              <span className="mono bloco-num">{v == null ? '—' : Math.round(v)}</span>
            </Ring>
          ))}
        </div>
      </HoloPanel>
      <HoloPanel id="bloco bloco-custo" rect={ap.custo} i={1} label="Custo">
        <span className="bloco-rot">Custo</span>
        <Ring value={costs?.uso_pct ?? 0} size={48} stroke={4} color={costs?.estado === 'teto' ? 'var(--danger)' : 'var(--aurora-2)'} label="Uso do teto mensal">
          <span className="mono bloco-num">{Math.round(costs?.uso_pct ?? 0)}%</span>
        </Ring>
        <span className="bloco-txt"><b className="mono">{usd(costs?.mes_usd)}</b> no mês</span>
      </HoloPanel>
      <HoloPanel id="bloco bloco-modelo" rect={ap.modelo} i={2} label="Modelo">
        <span className="bloco-rot">Modelo</span>
        <span className="bloco-modelo" style={{ color: tier.ui }}>{neural ? tier.label : '—'}</span>
        <span className="bloco-txt mono">{uso ? `US$ ${(uso.custo_usd ?? 0).toFixed(4).replace('.', ',')}` : 'sem turno'}</span>
      </HoloPanel>
    </>
  )
})

/** Detalhes do item selecionado no palco; sem seleção, a legenda da categoria. */
export function Detalhes({ rect, dados, selecionado }) {
  const it = dados.itens.find(x => x.id === selecionado)
  const g = it && dados.grupos[it.grupo]
  if (!it) {
    const conta = id => dados.itens.filter(x => x.grupo === id).length
    return (
      <HoloPanel id="detalhes" rect={rect} i={3} title="Projetos" label="Detalhes do palco">
        <p className="holo-det-resumo">{dados.itens.length} projetos. Clique num nó ou num nome para ver os detalhes.</p>
        <ul className="holo-det-grupos">
          {Object.entries(dados.grupos).map(([id, gr]) => (
            <li key={id} style={{ '--c': gr.cor }}><span className="holo-det-ponto" />{gr.nome}<span className="mono">{conta(id)}</span></li>
          ))}
        </ul>
        <p className="holo-det-fonte">Tamanho do nó: commit mais recente. Linhas: {dados.ligacoes.length} ligações. {dados.fonte}</p>
      </HoloPanel>
    )
  }
  const lig = dados.ligacoes.filter(l => l.de === it.id || l.para === it.id)
  const nome = id => dados.itens.find(x => x.id === id)?.nome || id
  return (
    <HoloPanel id="detalhes" rect={rect} i={3} title={it.nome} label={`Detalhes de ${it.nome}`}
      aside={<span className="chip" style={{ '--chip': g?.cor }}>{g?.nome}</span>}>
      <p className="holo-det-resumo">{it.resumo}</p>
      {it.stack.length > 0 && <ul className="holo-det-stack">{it.stack.map(s => <li key={s}>{s}</li>)}</ul>}
      <dl className="kv">
        <div><dt>Último commit</dt><dd className="mono">{it.ultimo ? data(it.ultimo) : 'sem histórico git'}</dd></div>
      </dl>
      {lig.length > 0 && (
        <>
          <h3 className="holo-sub">Ligações</h3>
          <ul className="holo-det-lig">
            {lig.map(l => <li key={`${l.de}-${l.para}`}><b>{nome(l.de === it.id ? l.para : l.de)}</b> · {l.motivo}</li>)}
          </ul>
        </>
      )}
      <p className="holo-det-fonte mono">{it.pasta}</p>
    </HoloPanel>
  )
}

