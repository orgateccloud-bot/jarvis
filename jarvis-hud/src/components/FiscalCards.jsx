import { useState } from 'react'
import { Card } from './Cards.jsx'
import {
  CAMPOS_CLIENTE, GRUPOS, ROTULO_ORIGEM, dataBR, dataHoraBR, fontesComProblema, formatarCampo, ordenar, severidade,
  textoPrazo,
} from '../lib/fiscal.js'

/** Avisos de fonte com problema: o card segue com os últimos dados válidos. */
function AvisoFontes({ fontes, erro }) {
  const falhas = fontesComProblema(fontes)
  if (!falhas.length && !erro) return null
  return (
    <ul className="fiscal-avisos" role="status">
      {erro && <li>Sem resposta do núcleo ({erro}): mostrando os últimos dados recebidos.</li>}
      {falhas.map(f => (
        <li key={f.id} title={f.erro || ''}>
          {f.nome} falhou na coleta de {dataHoraBR(f.ultima_coleta)}
          {f.ultimo_sucesso ? `: mostrando os últimos dados válidos, de ${dataHoraBR(f.ultimo_sucesso)}.` : ': ainda sem dados desta fonte.'}
        </li>
      ))}
    </ul>
  )
}

const VISIVEIS = 4 // itens por grupo antes do "ver todos": a coluna é estreita

function Fonte({ item }) {
  const curto = item.fonte_nome.split(' · ')[0] // "Receita Federal · Agenda Tributária" → "Receita Federal"
  if (item.fonte_url) {
    return (
      <a className="fiscal-fonte" href={item.fonte_url} target="_blank" rel="noopener noreferrer"
        title={`${item.fonte_nome}: ${item.fonte_url}`}>{curto}</a>
    )
  }
  return <span className="fiscal-fonte fiscal-fonte-interna" title={item.fonte_nome}>{item.fonte_nome}</span>
}

function Item({ item, hoje }) {
  const sev = severidade(item, hoje)
  return (
    <li className={`fiscal-item sev-${sev}`} title={item.detalhe || undefined}>
      <span className="fiscal-titulo">{item.titulo}</span>
      <span className="fiscal-meta">
        <span className="mono">{textoPrazo(item, hoje)}</span>
        {item.origem !== 'oficial' && (
          <span className={`fiscal-origem origem-${item.origem}`}>{ROTULO_ORIGEM[item.origem]}</span>
        )}
        <Fonte item={item} />
      </span>
    </li>
  )
}

function Grupo({ grupo, itens, vazio, hoje }) {
  const [todos, setTodos] = useState(false)
  const mostrados = todos ? itens : itens.slice(0, VISIVEIS)
  return (
    <section className="fiscal-grupo" aria-label={grupo.titulo}>
      <h3>{grupo.titulo}{itens.length > 0 && <span className="fiscal-contagem">{itens.length}</span>}</h3>
      {itens.length ? (
        <ul className="fiscal-lista">{mostrados.map(i => <Item key={i.id} item={i} hoje={hoje} />)}</ul>
      ) : (
        <p className="muted small">{vazio}</p>
      )}
      {itens.length > VISIVEIS && (
        <button type="button" className="fiscal-mais" onClick={() => setTodos(t => !t)} aria-expanded={todos}>
          {todos ? 'Mostrar menos' : `Ver todos (${itens.length})`}
        </button>
      )}
    </section>
  )
}

/** Card tributário: prazos, legislação, situação do cliente e pendências internas, cada item com fonte e data. */
export function TributarioCard({ painel, erro, atualizando, onAtualizar, hoje = new Date() }) {
  return (
    <Card
      title="Tributário"
      className="fiscal"
      aside={
        <button type="button" className="chip" onClick={onAtualizar} disabled={atualizando}
          title="Coletar agora as fontes oficiais e as fontes de clientes">
          {atualizando ? 'Atualizando…' : 'Atualizar'}
        </button>
      }
    >
      <p className="muted small fiscal-atualizado">
        {painel ? `Atualizado em ${dataHoraBR(painel.atualizado_em)}` : 'Aguardando o núcleo…'}
      </p>
      <AvisoFontes fontes={painel?.fontes} erro={erro} />
      {painel && GRUPOS.map(g => (
        <Grupo key={g.chave} grupo={g} itens={ordenar(painel.grupos[g.chave] || [], hoje)} hoje={hoje}
          vazio={g.chave === 'situacao' && painel.cliente_id ? 'Sem dados de situação deste cliente.' : g.vazio} />
      ))}
    </Card>
  )
}

/** Card do cliente: os dados para o trabalho contábil, com a fonte de cada campo e os conflitos entre fontes. */
export function ClienteCard({ clientes = [], clienteId, onEscolher, cliente, erro }) {
  const conflitos = new Map((cliente?.conflitos || []).map(c => [c.campo, c.valores]))
  return (
    <Card title="Cliente" className="fiscal cliente">
      <label className="fiscal-seletor">
        <span className="sr-only">Cliente</span>
        <select value={clienteId || ''} onChange={e => onEscolher(e.target.value)}>
          <option value="">{clientes.length ? 'Escolha um cliente…' : 'Nenhum cliente cadastrado'}</option>
          {clientes.map(c => <option key={c.id} value={c.id}>{c.nome} · {c.documento_mascarado}</option>)}
        </select>
      </label>
      <AvisoFontes fontes={cliente?.fontes} erro={erro} />
      {cliente ? (
        <dl className="fiscal-campos">
          {CAMPOS_CLIENTE.filter(([campo]) => cliente.campos[campo]).map(([campo, rotulo]) => {
            const c = cliente.campos[campo]
            const conflito = conflitos.get(campo)
            return (
              <div key={campo} className={c.antigo ? 'antigo' : undefined}>
                <dt>{rotulo}</dt>
                <dd>
                  <span className="fiscal-valor">{formatarCampo(campo, c.valor)}</span>
                  <span className="fiscal-fonte fiscal-fonte-interna"
                    title={c.atualizado_em ? `atualizado em ${dataHoraBR(c.atualizado_em)}` : undefined}>
                    {c.fonte_nome}{c.antigo ? ' · último dado válido' : ''}
                  </span>
                  {conflito && (
                    <span className="fiscal-conflito" title={Object.entries(conflito).map(([f, v]) => `${f}: ${formatarCampo(campo, v)}`).join('\n')}>
                      fontes divergem
                    </span>
                  )}
                </dd>
              </div>
            )
          })}
        </dl>
      ) : (
        <p className="muted small">
          {clientes.length ? 'Escolha um cliente para ver os dados.' : 'Cadastre clientes pela API (POST /painel/clientes) ou configure uma planilha.'}
        </p>
      )}
      {cliente && <p className="muted small">Gerado em {dataBR(cliente.gerado_em)} {dataHoraBR(cliente.gerado_em).split(' ')[1]}</p>}
    </Card>
  )
}
