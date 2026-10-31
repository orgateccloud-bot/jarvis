import { useCallback, useEffect, useState } from 'react'
import { getJson, postJson } from '../lib/api.js'

const CONSULTA_MS = 3000
const CONSULTA_DESLIGADA_MS = 30000 // flag em 0 (404): só confere de novo de vez em quando (ligar exige reiniciar a API)
const RENOVA_MS = 5000 // a API concede o microfone ao HUD por 15 s; renovando a cada 5 s, ele só vence se o HUD sumir

/**
 * Serviço de voz local (Etapa 2). voz: null = desligado (a API responde 404 em /voz, JARVIS_VOZ_LOCAL=0);
 * senão { estado, dono, situacao }. `ativo` = o serviço é o dono do microfone e do alto-falante agora.
 */
export function useVozLocal({ online, authOk }) {
  const [voz, setVoz] = useState(null)
  const [doHud, setDoHud] = useState(false)

  useEffect(() => {
    if (!online || !authOk) return
    let vivo = true
    let timer = 0
    const tick = async () => {
      let espera = CONSULTA_MS
      try {
        const v = await getJson('/voz')
        if (vivo) setVoz(v)
      } catch (e) {
        if (e.status === 404) {
          espera = CONSULTA_DESLIGADA_MS
          if (vivo) setVoz(null)
        }
      }
      if (vivo) timer = setTimeout(tick, espera)
    }
    tick()
    return () => { vivo = false; clearTimeout(timer) }
  }, [online, authOk])

  useEffect(() => {
    if (!doHud) return
    const id = setInterval(() => { postJson('/voz/dono', { dono: 'hud' }).catch(() => {}) }, RENOVA_MS)
    return () => clearInterval(id)
  }, [doHud])

  const pegarMicrofone = useCallback(async () => {
    await postJson('/voz/dono', { dono: 'hud' })
    setDoHud(true)
  }, [])
  const devolver = useCallback(async () => {
    setDoHud(false)
    await postJson('/voz/dono', { dono: 'servico' }).catch(() => {})
  }, [])
  const comando = useCallback(acao => { postJson('/voz/comando', { acao }).catch(() => {}) }, [])
  // evento "voz" do /events: o estado muda na hora, sem esperar a próxima consulta
  const aoEvento = useCallback(estado => setVoz(v => (v ? { ...v, estado } : v)), [])

  return { voz, ativo: !!voz && !doHud, doHud, pegarMicrofone, devolver, comando, aoEvento }
}
