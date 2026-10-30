import { useEffect, useState } from 'react'

const ler = () => ({ W: window.innerWidth, H: window.innerHeight })

/** Tamanho da janela, atualizado no máximo uma vez por quadro durante o redimensionamento. */
export function useViewport() {
  const [view, setView] = useState(ler)
  useEffect(() => {
    let raf = 0
    const onResize = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => setView(ler()))
    }
    window.addEventListener('resize', onResize)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', onResize)
    }
  }, [])
  return view
}
