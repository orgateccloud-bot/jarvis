import { useCallback, useEffect, useState } from 'react'
import { getJson, postJson } from '../lib/api.js'

const INTERVALO_MS = 60000
const CHAVE_CLIENTE = 'jarvis-cliente'

function lerCliente() {
  try { return Number(localStorage.getItem(CHAVE_CLIENTE)) || null } catch { return null }
}

/**
 * Painel fiscal: card tributário, lista de clientes e o cliente escolhido (lembrado no navegador).
 * Atualiza a cada 60 s e na troca de cliente. Se a busca falhar, mantém os últimos dados e informa o erro.
 */
export function usePainelFiscal({ online, authOk }) {
  const [clientes, setClientes] = useState([])
  const [clienteId, setClienteId] = useState(lerCliente)
  const [tributario, setTributario] = useState(null)
  const [cliente, setCliente] = useState(null)
  const [erro, setErro] = useState(null)
  const [atualizando, setAtualizando] = useState(false)
  const [rodada, setRodada] = useState(0)

  useEffect(() => {
    if (!online || !authOk) return
    let vivo = true
    const carregar = async () => {
      try {
        const [lista, card, detalhe] = await Promise.all([
          getJson('/painel/clientes'),
          getJson(`/painel/tributario${clienteId ? `?cliente=${clienteId}` : ''}`),
          clienteId ? getJson(`/painel/clientes/${clienteId}`) : Promise.resolve(null),
        ])
        if (!vivo) return
        setClientes(lista)
        setTributario(card)
        setCliente(detalhe)
        setErro(null)
      } catch (e) {
        if (!vivo) return
        if (e.status === 404 && clienteId) { // cliente apagado ou de outro banco: volta para "sem cliente"
          setClienteId(null)
          return
        }
        setErro(e.status ? `HTTP ${e.status}` : 'núcleo sem resposta') // os últimos dados continuam na tela
      }
    }
    carregar()
    const id = setInterval(carregar, INTERVALO_MS)
    return () => { vivo = false; clearInterval(id) }
  }, [online, authOk, clienteId, rodada])

  const escolher = useCallback(id => {
    const valor = Number(id) || null
    try {
      if (valor) localStorage.setItem(CHAVE_CLIENTE, String(valor))
      else localStorage.removeItem(CHAVE_CLIENTE)
    } catch { /* armazenamento indisponível */ }
    setClienteId(valor)
  }, [])

  const atualizarAgora = useCallback(async () => {
    setAtualizando(true)
    try {
      await postJson('/painel/atualizar')
    } catch (e) {
      setErro(e.status ? `HTTP ${e.status}` : 'núcleo sem resposta')
    } finally {
      setAtualizando(false)
      setRodada(r => r + 1)
    }
  }, [])

  return { clientes, clienteId, escolher, tributario, cliente, erro, atualizando, atualizarAgora }
}
