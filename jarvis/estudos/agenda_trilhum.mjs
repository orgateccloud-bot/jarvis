// Agenda de um plano do Trilhum calculada pelo próprio app (trilha.html), num navegador simulado (jsdom) e sem
// tela, do mesmo jeito que os testes do Trilhum abrem o app. Assim o JARVIS-TRILHUM não copia a lógica do
// calendário (fases, data-alvo, fase extra, reta final, rodízio de tópicos, sábados) e nunca diverge do app.
//
//     node agenda_trilhum.mjs <trilha.html> <plano.json> <pasta node_modules com o jsdom>
//
// Só lê: nada é gravado na Trilha. O localStorage é o do navegador simulado e some ao terminar.
// Saída (stdout): JSON com as semanas, os dias, os blocos e as fases.
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {join} from 'node:path';

const [htmlPath, planoPath, modulos] = process.argv.slice(2);
if (!htmlPath || !planoPath || !modulos) {
  process.stderr.write('uso: node agenda_trilhum.mjs <trilha.html> <plano.json> <node_modules>\n');
  process.exit(2);
}
const {JSDOM, VirtualConsole} = createRequire(join(modulos, 'jsdom.cjs'))('jsdom');
const plano = JSON.parse(readFileSync(planoPath, 'utf8'));

// O app guarda as semanas em `S`, dentro de uma função fechada. Na cópia em memória (o arquivo não muda), um
// gancho logo depois de montar as semanas as expõe a este script. Se o trecho mudar no app, falha em vez de chutar.
const GANCHO = 'function renderAll(){S=buildWeeks();';
const html = readFileSync(htmlPath, 'utf8');
if (html.split(GANCHO).length !== 2) {
  process.stderr.write('trilha.html mudou: não achei o ponto onde o app monta as semanas (' + GANCHO + ')\n');
  process.exit(3);
}

const dom = new JSDOM(html.replace(GANCHO, GANCHO + 'window.__jarvis={S,phases};'), {
  url: 'http://localhost/app',
  runScripts: 'dangerously',
  pretendToBeVisual: true,
  virtualConsole: new VirtualConsole(), // o app escreve no console; aqui só interessa o JSON
  beforeParse(w) {
    w.localStorage.setItem('trilha.planos', JSON.stringify({[plano.id]: plano}));
    w.localStorage.setItem('trilha.ativo', JSON.stringify(plano.id));
    w.localStorage.setItem('trilha.' + plano.id + '.perfil', JSON.stringify({nome: 'JARVIS', proj: plano.sigla, cargo: plano.nome}));
    w.matchMedia = () => ({matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}});
    w.scrollTo = () => {};
    w.HTMLElement.prototype.scrollIntoView = () => {};
  },
});

const hhmm = (m) => (m == null ? null : String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(m % 60).padStart(2, '0'));
try {
  if (!dom.window.__jarvis) {
    process.stderr.write('o app não montou as semanas (plano inválido?)\n');
    process.exit(4);
  }
  const bruto = dom.window.eval(`const {S, phases} = window.__jarvis; JSON.stringify({
    total: S.total,
    semanas: S.weeks.map((w) => ({n: w.n, segunda: w.mon, fase: w.fase, titulo: w.tit,
      dias: w.days.map((d) => ({data: d.date, feriado: d.fer || '', depois_da_prova: !!d.after,
        blocos: d.blocks.map((b) => ({tipo: b.label, disciplina: b.disc, assunto: b.topic, minutos: b.min,
          inicio: b.start, questoes: b.nq}))}))})),
    fases: phases().map((p) => ({nome: p.name, descricao: p.desc || '', saida: p.out || '',
      inicio: p.r ? p.r[0] : null, fim: p.r ? p.r[1] : null}))
  })`);
  const agenda = JSON.parse(bruto);
  agenda.semanas.forEach((s) => s.dias.forEach((d) => d.blocos.forEach((b) => { b.inicio = hhmm(b.inicio); })));
  process.stdout.write(JSON.stringify(agenda));
} finally {
  dom.window.close(); // o app tem timers: sem isso o processo não termina
}
