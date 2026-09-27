/**
 * A mensagem do compartilhamento do relatório.
 *
 * Fica em `lib/` e não junto do componente por dois motivos: o `react-refresh` do Vite
 * exige que um arquivo de componente exporte **só** componentes, e o texto é a parte que
 * um teste precisa afirmar isoladamente.
 *
 * **Sem nome, sem telefone, sem "olá {cliente}".** A mensagem descreve o documento, não o
 * destinatário: o produto não sabe quem vai receber, e não tem campo para saber.
 */
export function mensagemDeCompartilhamento(
  rotuloFord: string,
  rotuloConcorrente: string,
): string {
  return (
    `Comparativo técnico: ${rotuloFord} × ${rotuloConcorrente}. ` +
    'Cada número tem a fonte e a data da coleta no documento.'
  )
}
