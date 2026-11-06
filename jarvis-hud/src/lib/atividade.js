// O que o JARVIS está fazendo agora, em poucas palavras, para a legenda sob o astro. Puro, para ser testável.
// O `resumo` do evento `tool` não serve aqui: ele fala no passado ("consultou os custos") e pode ser longo.
// A lista inclui as ferramentas dos outros JARVIS para o arquivo ser igual em todos os branches.

const ROTULOS = {
  buscar_conhecimento: 'Consultando a base',
  memory: 'Acessando a memória',
  web_search: 'Buscando na web',
  web_fetch: 'Lendo a página',
  code_execution: 'Rodando no sandbox',
  bash_code_execution: 'Rodando no sandbox',
  text_editor_code_execution: 'Rodando no sandbox',

  status_sistema: 'Lendo o sistema',
  hardware_info: 'Lendo o sistema',
  processos_pesados: 'Olhando os processos',
  encerrar_processo: 'Encerrando o processo',
  comando_seguro: 'Rodando o comando',
  abrir_configuracao: 'Abrindo a configuração',

  listar_pasta: 'Procurando nos arquivos',
  buscar_arquivos: 'Procurando nos arquivos',
  ler_arquivo: 'Lendo o arquivo',
  analisar_espaco: 'Analisando o disco',
  mover_itens: 'Movendo os arquivos',
  enviar_para_lixeira: 'Enviando para a Lixeira',
  desfazer_movimento: 'Desfazendo o movimento',
  movimentos_recentes: 'Vendo os movimentos',

  custos: 'Conferindo os custos',
  criar_lembrete: 'Criando o lembrete',
  lembretes_listar: 'Vendo os lembretes',
  cancelar_lembrete: 'Cancelando o lembrete',

  abrir_app: 'Abrindo o programa',
  listar_apps: 'Vendo os programas',
  apps_abertos: 'Vendo as janelas abertas',

  agentes_status: 'Olhando os agentes',
  comandar_agente: 'Acionando o agente',
  resultado_agente: 'Lendo o resultado do agente',
  gerenciar_agente: 'Ajustando o agente',

  trilhum_agenda: 'Abrindo a agenda de estudos',
  trilhum_progresso: 'Conferindo o progresso',
  trilhum_planos: 'Vendo os planos de estudo',
  trilhum_plano: 'Lendo o plano de estudo',
}

export const ESPERA = 'Aguardando a sua confirmação'

/** Rótulo de uma ferramenta; a que não está na lista cai em "Trabalhando". */
export const rotuloDaFerramenta = nome => ROTULOS[nome] || 'Trabalhando'

/** Fase depois de um evento `tool`: a ferramenta que começa é trabalho; a que termina libera a espera de aprovação. */
export function faseDepoisDaFerramenta(fase, evento) {
  if (evento.fase === 'inicio') return 'thinking'
  return fase === 'waiting' ? 'thinking' : fase
}
