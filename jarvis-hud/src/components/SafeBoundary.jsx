import { Component } from 'react'

/** Isola falhas de renderização: um trecho com erro mostra o fallback em vez de derrubar o HUD inteiro. */
export default class SafeBoundary extends Component {
  state = { error: null, key: this.props.resetKey }

  static getDerivedStateFromError(error) {
    return { error }
  }

  static getDerivedStateFromProps(props, state) {
    // conteúdo novo (ex.: mais texto do stream) → tenta renderizar de novo
    return props.resetKey !== state.key ? { error: null, key: props.resetKey } : null
  }

  componentDidCatch(error) {
    console.error('SafeBoundary:', error)
  }

  render() {
    return this.state.error ? this.props.fallback : this.props.children
  }
}
