// Gera as saídas esperadas de tests/fixtures/voz/casos.json a partir do código do HUD (a referência).
// O serviço de voz local (jarvis/voz/texto.py e eco.py) precisa dar as mesmas saídas: pytest e npm test conferem.
//   node scripts/gerar_casos_voz.mjs
import { readFileSync, writeFileSync } from 'node:fs'
import { createEchoFilter } from '../jarvis-hud/src/lib/voice/echo.js'
import { NO, YES, createSentenceSplitter, paraFala } from '../jarvis-hud/src/lib/voice/sentences.js'

const arquivo = new URL('../tests/fixtures/voz/casos.json', import.meta.url)
const casos = JSON.parse(readFileSync(arquivo, 'utf8'))

const PARA_FALA = [
  'O log está em D:\\JARVIS-Arquivo\\Gerados\\2026-10-30\\prompt_voz_eco.md.',
  'Veja https://www.receita.fazenda.gov.br/consulta?id=1 hoje',
  'o arquivo ~/projetos/jarvis/config.json',
  'rode "npm test" e `npm run build`',
  'saldo de R$ 15.000,00 e R$ 2 mil',
  'alta de 3,5% no mês e 12 %',
  'e/ou 1/2 de 30/10/2026',
  'Caminho: C:\\a\\b\\c.txt; veja.',
  'site www.planalto.gov.br/ccivil_03/leis/l5172.htm',
]

// cada caso: [lista de trechos que chegam em streaming]; "*" no começo = mandar caractere a caractere
const DIVISOR = [
  ['*O Sol perde **4 milhões** de toneladas por segundo. Mesmo assim, deve durar mais 5 bilhões de anos.\n\n'
    + '| Café | Chá |\n|---|---|\n| forte | leve |\n\n```python\nprint(1)\n```\n'
    + '- Primeiro item da lista com bastante texto\n- Segundo item\n\nEm resumo, o valor é 3.5 vezes maior.'],
  ['*Resultado: o balancete fechou; o saldo bate com o extrato do banco e não há diferenças a conciliar. Pronto.'],
  ['*' + 'Conferi os lançamentos de janeiro a abril da transportadora, '.repeat(6) + 'e não encontrei divergências.'],
  ['Sim. ', 'Feito. ', 'O lembrete está criado para amanhã.'],
  ['*Caminho: C:\\a\\b\\c.txt; veja.'],
  ['Bom dia, Senhor. ', 'O disco C está com 82% de uso e o arquivo ficou em D:\\JARVIS-Arquivo\\Gerados\\relatorio_mensal.xlsx. ',
    'Quer que eu mova os downloads antigos?'],
]

const SIM_NAO = ['sim', 'sim pode abrir', 'Pode sim', 'ok', 'Ok, Jarvis', 'não', 'não, cancela', 'nao', 'cancelar',
  'nem pensar', 'talvez', 'simplesmente não']

// cenários do filtro de eco: o JARVIS falou `lembrar`, a fala terminou (ou não), passaram `passa_ms` e ouviu `ouvido`
const ECO = [
  { lembrar: ['O script para iniciar no logon fica na pasta scripts do projeto.', 'Ele registra uma tarefa no Agendador do Windows.'], terminou: true, passa_ms: 2000, ouvido: 'o script para iniciar no logon' },
  { lembrar: ['O script para iniciar no logon fica na pasta scripts do projeto.', 'Ele registra uma tarefa no Agendador do Windows.'], terminou: true, passa_ms: 2000, ouvido: 'fica na pasta scripts do projeto ele registra' },
  { lembrar: ['O script para iniciar no logon fica na pasta scripts do projeto.'], terminou: true, passa_ms: 2000, ouvido: 'script iniciar logon pasta' },
  { lembrar: ['O script para iniciar no logon fica na pasta scripts do projeto.'], terminou: true, passa_ms: 1500, ouvido: 'qual a previsão do tempo para amanhã' },
  { lembrar: ['O script para iniciar no logon fica na pasta scripts do projeto.'], terminou: true, passa_ms: 1500, ouvido: 'onde fica o script de logon' },
  { lembrar: ['O script para iniciar no logon fica na pasta scripts do projeto.'], terminou: true, passa_ms: 8500, ouvido: 'o script para iniciar no logon' },
  { lembrar: ['Primeira frase sobre o balancete de setembro.'], terminou: false, passa_ms: 60000, ouvido: 'balancete de setembro' },
  { lembrar: ['Confirma: abrir o Chrome? Diga sim ou não.'], terminou: true, passa_ms: 1600, ouvido: 'sim', resposta: true },
  { lembrar: ['Confirma: abrir o Chrome? Diga sim ou não.'], terminou: true, passa_ms: 1600, ouvido: 'sim ou não', resposta: true },
  { lembrar: ['Confirma: abrir o Chrome? Diga sim ou não.'], terminou: true, passa_ms: 1600, ouvido: 'confirma abrir o chrome' },
]

casos.paraFala = PARA_FALA.map(t => [t, paraFala(t)])
casos.divisor = DIVISOR.map(trechos => {
  const out = []
  const sp = createSentenceSplitter(s => out.push(s))
  for (const t of trechos) {
    if (t.startsWith('*')) for (const c of t.slice(1)) sp.push(c)
    else sp.push(t)
  }
  sp.flush()
  return [trechos, out]
})
casos.simNao = SIM_NAO.map(t => [t, YES.test(t), NO.test(t)])
casos.eco = ECO.map(c => {
  let agora = 1_000_000
  const f = createEchoFilter({ now: () => agora })
  for (const l of c.lembrar) f.remember(l)
  if (c.terminou) f.ended()
  agora += c.passa_ms
  return { ...c, eco: f.isEcho(c.ouvido, { answer: !!c.resposta }) }
})
writeFileSync(arquivo, JSON.stringify(casos, null, 2) + '\n')
console.log(`paraFala ${casos.paraFala.length}, divisor ${casos.divisor.length}, simNao ${casos.simNao.length}, eco ${casos.eco.length}`)
