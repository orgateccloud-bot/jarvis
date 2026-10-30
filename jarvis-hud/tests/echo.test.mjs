// Testes do filtro de eco (o JARVIS não pode responder à própria voz). Rode: npm test
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createEchoFilter, tokens } from '../src/lib/voice/echo.js'
import { routeHeard } from '../src/lib/voice/route.js'

function relogio() {
  let t = 1_000_000
  return { now: () => t, passa: ms => { t += ms } }
}

test('tokens: sem acento, sem pontuação, minúsculas', () => {
  assert.deepEqual(tokens('Atenção: o JARVIS já começou, né?'), ['atencao', 'o', 'jarvis', 'ja', 'comecou', 'ne'])
})

test('eco da frase anterior após speakEnd NÃO chama ask() nem cancel()', () => {
  const r = relogio()
  const echo = createEchoFilter({ now: r.now })
  echo.remember('O script para iniciar no logon fica na pasta scripts do projeto.')
  echo.remember('Ele registra uma tarefa no Agendador do Windows.')
  echo.ended()
  r.passa(2000)
  const ctx = { mode: 'active', speaking: false, busy: false, pendingApproval: false, isEcho: echo.isEcho }
  for (const eco of ['o script para iniciar no logon', 'fica na pasta scripts do projeto ele registra',
    'script iniciar logon pasta', 'agendador do windows', 'Jarvis para iniciar no logon'])
    assert.deepEqual(routeHeard(eco, true, ctx), { action: 'ignore', echo: true }, eco)
  // durante a fala também (barge-in com fone): eco com "para" não interrompe
  assert.equal(routeHeard('o script para iniciar', true, { ...ctx, speaking: true }).action, 'ignore')
})

test('pergunta nova do usuário passa; depois da janela de 8 s o eco não vale mais', () => {
  const r = relogio()
  const echo = createEchoFilter({ now: r.now })
  echo.remember('O script para iniciar no logon fica na pasta scripts do projeto.')
  echo.ended()
  r.passa(1500)
  assert.ok(!echo.isEcho('qual a previsão do tempo para amanhã'))
  assert.ok(!echo.isEcho('onde fica o script de logon'))
  r.passa(7000)
  assert.ok(!echo.isEcho('o script para iniciar no logon'))
})

test('a fala em curso conta como recente até terminar; guarda só as últimas 6 frases', () => {
  const r = relogio()
  const echo = createEchoFilter({ now: r.now })
  echo.remember('Primeira frase sobre o balancete de setembro.')
  r.passa(60_000)  // ainda falando: sem speakEnd a janela não começa
  assert.ok(echo.isEcho('balancete de setembro'))
  for (let i = 0; i < 6; i++) echo.remember(`Frase número ${i} com conteúdo diferente.`)
  assert.ok(!echo.isEcho('primeira frase sobre o balancete'))
})

test('confirmação: o "sim" do usuário passa; o eco de "Confirma… Diga sim ou não" não aprova', () => {
  const r = relogio()
  const echo = createEchoFilter({ now: r.now })
  echo.remember('Confirma: abrir o Chrome? Diga sim ou não.')
  echo.ended()
  r.passa(1600)
  const ctx = { mode: 'active', speaking: false, busy: false, pendingApproval: true, isEcho: echo.isEcho }
  assert.deepEqual(routeHeard('sim', true, ctx), { action: 'approve', ok: true })
  assert.deepEqual(routeHeard('não', true, ctx), { action: 'approve', ok: false })
  assert.deepEqual(routeHeard('sim, pode abrir o Chrome', true, ctx), { action: 'approve', ok: true })
  assert.equal(routeHeard('confirma abrir o chrome', true, ctx).action, 'ignore')
  assert.equal(routeHeard('sim ou não', true, ctx).action, 'ignore')
})
