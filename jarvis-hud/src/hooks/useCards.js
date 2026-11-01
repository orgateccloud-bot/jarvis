import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { alternar, alternarTodos, lerMinimizados, salvarMinimizados } from '../lib/telaLimpa.js'

/** Cards minimizados do HUD. O App cria o estado e o entrega pelo contexto; cada Card se registra e lê o seu. */
export const CardsContexto = createContext(null)

export function useCardsMinimizados() {
  const [minimizados, setMinimizados] = useState(lerMinimizados)
  const [ids, setIds] = useState([])
  useEffect(() => salvarMinimizados(minimizados), [minimizados])

  const registrar = useCallback(id => {
    setIds(l => (l.includes(id) ? l : [...l, id]))
    return () => setIds(l => l.filter(x => x !== id))
  }, [])
  const alternarCard = useCallback(id => setMinimizados(l => alternar(l, id)), [])
  const alternarTodosCards = useCallback(() => setMinimizados(l => alternarTodos(l, ids)), [ids])
  const todosMinimizados = ids.length > 0 && ids.every(id => minimizados.includes(id))

  return useMemo(() => ({ minimizados, registrar, alternarCard, alternarTodosCards, todosMinimizados }),
    [minimizados, registrar, alternarCard, alternarTodosCards, todosMinimizados])
}

/** Estado de um card. Sem o contexto (testes, telas isoladas), o card fica sempre aberto. */
export function useCard(id) {
  const ctx = useContext(CardsContexto)
  const registrar = ctx?.registrar
  const alternarCard = ctx?.alternarCard
  useEffect(() => registrar?.(id), [registrar, id])
  const alternarEste = useCallback(() => alternarCard?.(id), [alternarCard, id])
  return { minimizado: Boolean(ctx?.minimizados.includes(id)), alternar: alternarEste }
}
