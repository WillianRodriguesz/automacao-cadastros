# automacao-cadastros

Automação em Python que lê solicitações cadastrais de um arquivo JSON, seleciona as aprovadas que têm CPF informado e gera um CSV para uso por outras áreas. Toda a execução é registrada em um arquivo de log.

Repositório: https://github.com/WillianRodriguesz/automacao-cadastros

## Pré-requisitos

- Python 3.10 ou superior (testado com 3.10, 3.13 e 3.14). Usa apenas a biblioteca padrão, então não há `requirements.txt`.
- Alternativa: Docker com Compose, sem instalar Python na máquina.

## Estrutura

```
automacao-cadastros/
├── main.py             # aplicação: leitura, regras, CSV e log
├── test_main.py        # testes unitários (unittest)
├── solicitacoes.json   # entrada
├── Dockerfile
├── compose.yaml
├── .dockerignore
├── .gitignore
└── README.md
```

A execução cria `aprovados.csv` e `processamento.log` na mesma pasta do `main.py`.

## Como executar

Com Python:

```
python main.py
```

Os caminhos são resolvidos a partir da pasta do `main.py`, então o comando funciona de qualquer diretório.

Com Docker:

```
docker compose run --rm app
```

A primeira execução constrói a imagem. O compose monta a pasta do projeto no container, então `aprovados.csv` e `processamento.log` aparecem no seu disco.

Código de saída: `0` quando o processamento termina (mesmo que haja registros ignorados), `1` para falhas tratadas (entrada, saída ou log) e `2` para falhas inesperadas.

## Testes

```
python -m unittest -v
```

Ou, com Docker:

```
docker compose run --rm testes
```

São 27 testes em `test_main.py` (`unittest`, biblioteca padrão), um grupo por função:

| Grupo | O que cobre |
|---|---|
| `carregar_solicitacoes` | lista válida, arquivo com BOM, arquivo inexistente, JSON malformado, raiz que não é lista |
| `avaliar_registro` | registro elegível; cada motivo para ignorar (status, CPF nulo, vazio ou só espaços, campo ausente, item que não é objeto, nome ou id inválidos, texto fora de UTF-8); a ordem das verificações |
| `filtrar_aprovados` | separação entre aprovados e ignorados, ordem e remoção de espaços |
| `gerar_csv` | cabeçalho, vírgula, acentos em UTF-8 sem BOM, lista vazia, pasta inexistente, falha no meio da gravação sem perder o CSV anterior |
| `executar` | fluxo completo com o arquivo de exemplo (7 exportados, 8 ignorados) e as falhas tratadas: entrada inexistente, JSON inválido, falha ao gravar o CSV, log que não pode ser criado, falha inesperada; log em modo *append* |

Os testes usam pastas temporárias e só leem o `solicitacoes.json`.

## Formato de entrada

`solicitacoes.json` deve conter uma lista de objetos, em UTF-8 (BOM é aceito):

```json
[
  { "id": 1, "nome": "Maria Silva", "cpf": "12345678900", "status": "APROVADO" },
  { "id": 2, "nome": "Pedro Santos", "cpf": "45678912300", "status": "PENDENTE" }
]
```

| Campo | Tipo esperado |
|---|---|
| `id` | inteiro ou texto não vazio |
| `nome` | texto não vazio |
| `cpf` | texto |
| `status` | texto |

Chaves extras são ignoradas.

## Regras de filtragem

Um registro é exportado quando passa por todas as verificações abaixo. Em resumo: o `status` é exatamente `APROVADO`, e `cpf`, `nome` e `id` estão preenchidos e podem ser gravados em UTF-8. Os dígitos verificadores do CPF não são validados.

Os demais registros são ignorados um a um, com o motivo no log, sem interromper os outros. As verificações seguem esta ordem, e a primeira que falha define o motivo registrado:

| # | Verificação | Nível no log |
|---|---|---|
| 1 | o item é um objeto JSON | WARNING |
| 2 | existem as chaves `id`, `nome`, `cpf` e `status` | WARNING |
| 3 | `status` é igual a `APROVADO` | INFO |
| 4 | `cpf` é um texto preenchido (não nulo, não vazio, não só espaços) | WARNING |
| 5 | `nome` é um texto preenchido | WARNING |
| 6 | `id` é um inteiro ou um texto preenchido | WARNING |
| 7 | `id`, `nome` e `cpf` cabem em UTF-8 (um emoji cortado ao meio, por exemplo, não cabe) | WARNING |

Status diferente de `APROVADO` é regra de negócio (a solicitação ainda não foi aprovada), por isso fica em INFO. Os demais casos indicam dado incompleto ou inválido e ficam em WARNING. Por causa dessa ordem, uma solicitação `PENDENTE` com CPF vazio aparece no log como `PENDENTE`: o CPF só importa para quem foi aprovado.

## CSV gerado

`aprovados.csv`:

- UTF-8 sem BOM, com acentos preservados.
- Separador: vírgula.
- Colunas, nesta ordem: `id,nome,cpf`.
- Linhas terminadas em CRLF (padrão do módulo `csv`); campos com vírgula ou aspas são escapados.
- O arquivo é sobrescrito a cada execução. Sem registros elegíveis, ele contém só o cabeçalho.
- A gravação é feita em `aprovados.csv.tmp`, e o arquivo final só é trocado depois que tudo foi escrito. Se algo falhar no meio, o `aprovados.csv` anterior continua como estava e o temporário é removido.
- Uma execução que falha antes de gerar o CSV (entrada ausente ou inválida, por exemplo) não mexe no `aprovados.csv` de uma execução anterior: ele continua lá. Para saber se a última execução teve sucesso, use o código de saída ou o fim do log (`Resultado final`).

Ao abrir o CSV direto no Excel, os acentos podem aparecer errados (sem BOM, o Excel assume a codificação local) e CPFs com zero à esquerda podem perder o zero. Para evitar, use *Dados > De Texto/CSV*, escolha UTF-8 e defina a coluna `cpf` como texto. Os valores são gravados como vieram: um nome que comece com `=`, `+`, `-` ou `@` pode ser interpretado como fórmula pelo Excel.

## Log

`processamento.log` recebe o mesmo que aparece no console. Cada linha tem o formato:

```
AAAA-MM-DD HH:MM:SS | NÍVEL    | mensagem
```

A exceção são os tracebacks das falhas inesperadas, que ocupam várias linhas.

Uma execução registra, nesta ordem: início, arquivo lido, total de registros lidos, uma linha para cada item ignorado (com identificador e motivo), CSV gerado, total exportado, total ignorado, duração e resultado final (`SUCESSO` ou `FALHA`). Em caso de sucesso, lidos = exportados + ignorados.

O identificador é `id N` ou, quando o item não tem um id válido, a posição dele na lista (`posição N`). Ids de texto aparecem com escapes (`\n` no lugar de uma quebra de linha real), para que um valor vindo do JSON não consiga forjar linhas no log.

O arquivo é aberto em modo *append*: execuções repetidas acumulam histórico, cada uma começando em `Processamento iniciado`.

Execução real com o `solicitacoes.json` de exemplo (os caminhos aparecem como `/app/...` porque foi rodada no container):

```
2026-10-10 14:39:18 | INFO     | Processamento iniciado
2026-10-10 14:39:18 | INFO     | Lendo solicitações de /app/solicitacoes.json
2026-10-10 14:39:18 | INFO     | Total de registros lidos: 15
2026-10-10 14:39:18 | WARNING  | Registro ignorado (id 2): cpf vazio ou só espaços
2026-10-10 14:39:18 | INFO     | Registro ignorado (id 3): status 'PENDENTE' diferente de APROVADO
2026-10-10 14:39:18 | INFO     | Registro ignorado (id 5): status 'PENDENTE' diferente de APROVADO
2026-10-10 14:39:18 | INFO     | Registro ignorado (id 7): status 'REPROVADO' diferente de APROVADO
2026-10-10 14:39:18 | WARNING  | Registro ignorado (id 8): cpf vazio ou só espaços
2026-10-10 14:39:18 | INFO     | Registro ignorado (id 10): status 'PENDENTE' diferente de APROVADO
2026-10-10 14:39:18 | INFO     | Registro ignorado (id 11): status 'REPROVADO' diferente de APROVADO
2026-10-10 14:39:18 | INFO     | Registro ignorado (id 14): status 'PENDENTE' diferente de APROVADO
2026-10-10 14:39:18 | INFO     | CSV gerado: /app/aprovados.csv
2026-10-10 14:39:18 | INFO     | Registros exportados: 7
2026-10-10 14:39:18 | INFO     | Registros ignorados: 8
2026-10-10 14:39:18 | INFO     | Processamento concluído em 0.03s
2026-10-10 14:39:18 | INFO     | Resultado final: SUCESSO
```

O `aprovados.csv` gerado nessa execução:

```
id,nome,cpf
1,Maria Silva,12345678900
4,Pedro Santos,45678912300
6,Carlos Ferreira,74185296300
9,Patricia Martins,96385274100
12,Bruno Nunes,85274196300
13,Mariana Teixeira,15975348600
15,Aline Carvalho,32165498700
```

## Erros tratados

| Situação | Comportamento | Saída |
|---|---|---|
| `solicitacoes.json` não existe | ERROR `Arquivo de entrada não encontrado`; nenhum CSV é gerado | 1 |
| JSON malformado ou arquivo vazio | ERROR `JSON inválido`, com linha e coluna | 1 |
| Arquivo fora de UTF-8 | ERROR `Arquivo de entrada não está em UTF-8` | 1 |
| JSON válido, mas a raiz não é uma lista | ERROR `Estrutura inesperada`, com o tipo encontrado | 1 |
| Falha de leitura (permissão, caminho é pasta) | ERROR `Não foi possível ler` | 1 |
| Falha ao gravar o CSV (pasta inexistente, sem permissão, disco cheio, arquivo aberto em outro programa) | ERROR `Falha ao gravar o CSV`; o `aprovados.csv` anterior, se existir, fica intacto | 1 |
| Log não pode ser criado | mensagem em stderr; nada é processado | 1 |
| Item que não é objeto, campo ausente, CPF nulo ou vazio, nome ou id inválidos, texto que não cabe em UTF-8 | registro ignorado, WARNING com identificador e motivo; o processamento continua | 0 |
| `status` diferente de `APROVADO` | registro ignorado, INFO; o processamento continua | 0 |
| Qualquer outra falha, por exemplo um inteiro com mais de 4300 dígitos ou milhares de níveis de aninhamento no JSON (o Python recusa ambos ao ler o arquivo) | ERROR com traceback no log; nenhum CSV novo é gravado | 2 |

### Exemplos reais

Falhas de entrada ou saída terminam com as linhas `Processamento interrompido após ...s` e `Resultado final: FALHA` (a exceção é o log que não pode ser criado, que gera só a mensagem em stderr). A linha que descreve a causa, em três casos:

```
# solicitacoes.json ausente (código 1)
2026-10-10 14:39:19 | ERROR    | Arquivo de entrada não encontrado: /app/solicitacoes.json

# JSON malformado (código 1)
2026-10-10 14:39:20 | ERROR    | JSON inválido em /app/solicitacoes.json: Expecting ',' delimiter: line 1 column 77 (char 76)

# CSV impossível de gravar, aqui com uma pasta ocupando o nome aprovados.csv (código 1)
2026-10-10 14:39:22 | ERROR    | Falha ao gravar o CSV /app/aprovados.csv: [Errno 21] Is a directory: '/app/aprovados.csv.tmp' -> '/app/aprovados.csv'
```

Registros inválidos no meio do arquivo não derrubam a execução (código 0). Cada um vira uma linha no log:

```
2026-10-10 14:39:23 | WARNING  | Registro ignorado (id 2): campo(s) obrigatório(s) ausente(s): cpf
2026-10-10 14:39:23 | WARNING  | Registro ignorado (id 3): cpf nulo
2026-10-10 14:39:23 | WARNING  | Registro ignorado (posição 5): registro não é um objeto (tipo: str)
2026-10-10 14:39:23 | INFO     | Registro ignorado (id 6): status 'PENDENTE' diferente de APROVADO
```

## Premissas e decisões

- **Separador vírgula**, UTF-8 sem BOM. É o formato mais comum para consumo por outros sistemas; o impacto no Excel está descrito acima.
- **Comparação de status exata**: `aprovado` ou ` APROVADO` (com espaço) não são aceitos. O valor recebido aparece no motivo do log, o que facilita enxergar o problema no dado.
- **CPF** é gravado como veio, sem espaços nas pontas e sem reformatar (zeros à esquerda são mantidos). Só se verifica a presença.
- **Sem deduplicação**: ids repetidos são exportados como vieram.
- **Problemas em um registro nunca interrompem os demais** (campo ausente, tipo errado, texto inválido). Falhas de entrada ou saída interrompem, porque sem arquivo de origem ou de destino não há como continuar com segurança. A exceção são entradas absurdas que o Python recusa já ao ler o JSON (inteiros com mais de 4300 dígitos, milhares de níveis de aninhamento): terminam como falha inesperada, código 2.
- **CSV gravado em arquivo temporário e trocado no final**, para nunca deixar um arquivo parcial nem destruir o anterior numa falha.
- **Um único `except Exception`**, em `executar`, para falhas realmente inesperadas. Nos demais pontos os erros são tratados por tipo.
- **Estrutura em um único módulo.** O código é pequeno; a separação está nas funções: leitura, regra de elegibilidade (função pura, testável sem arquivos), geração do CSV e configuração do log.
- Os caminhos de entrada, saída e log são constantes no topo do `main.py`; a função `executar` recebe os três como parâmetros, o que permite testá-la em pastas temporárias.

## Ferramentas de IA utilizadas

Usei o **Claude Code** (Anthropic, modelo Claude Sonnet 5.5) na extensão do VS Code, em duas fases. Conduzi o processo: defini a estrutura, acompanhei cada etapa e decidi o que ficava.

**1. Esboço e fluxo com múltiplos agentes.** Parti do meu briefing (requisitos, colunas do CSV e itens do log) e defini a estrutura: um único módulo, sem camadas (DDD), testes simples e Docker como forma alternativa de executar. Com o Claude montei o esboço do projeto e uma especificação, com funções, mensagens de log e códigos de saída definidos de antemão, e testei um fluxo com múltiplos agentes a partir dela:

| Agente | Papel |
|---|---|
| Implementação | Escreveu alguns trechos da primeira versão do `main.py` a partir da especificação. |
| Revisão | Tentou quebrar o código com entradas hostis e comparou o README com o comportamento real. Apontou três problemas (CSV parcial depois de uma falha no meio da gravação, linhas de log que um `id` podia forjar, linha de log perdida com caractere inválido) e divergências no README. Todos foram corrigidos. |
| Testes independentes | Escreveu, só a partir da especificação e sem ver o código, uma suíte de 241 testes para conferir o `main.py`. Ela não faz parte do projeto: pedi testes unitários mais simples, só das funções principais. |

**2. Revisão e refino, trecho a trecho.** Com a primeira versão pronta, revisei o `main.py`, um trecho de cada vez: a cada passo eu pedia ajustes de nomenclatura, lógica e legibilidade, conferindo o resultado antes de seguir. Também questionei a performance (a filtragem foi medida e não precisou de ajuste). Entre as decisões que tomei:

- Simplificar o tratamento de erros, sem `try` dentro de `try`, e trocar números soltos por constantes nomeadas, como os códigos de saída.
- Ajustar a nomenclatura, por exemplo a classe `RegistroIgnorado` com os campos `id`, `mensagem` e `erro`.
- Concentrar e melhorar as regras de negócio em `avaliar_registro`.
- Recusar funções auxiliares que só teriam um chamador.

## Possíveis evoluções

**Integração com um fluxo de BPM.** O desenho seria:

1. Um formulário recebe a solicitação e a grava com `status` `PENDENTE` (em uma base de dados ou fila), em vez de depender de um arquivo diário.
2. Uma etapa de aprovação no BPM muda o `status` para `APROVADO` ou `REPROVADO`.
3. A transição para `APROVADO` dispara a automação, por webhook, evento ou agendamento.
4. A automação lê as solicitações aprovadas direto da base ou de uma API (só a função `carregar_solicitacoes` mudaria), aplica as mesmas regras de elegibilidade, gera o CSV e o entrega em uma pasta compartilhada ou serviço de transferência.
5. Os registros exportados são marcados como processados, para que uma nova execução não os repita, e o resultado (código de saída e log) é enviado ao monitoramento do BPM para alertar em caso de falha.

**Arquivos muito grandes.** Medi a execução com 1 milhão de registros (JSON de 89 MB): cerca de 11 s e 614 MB de memória no pico, porque o arquivo inteiro e as listas de resultado ficam em memória. Para volumes bem maiores:

- **Memória:** eu leria em streaming e processaria em lotes: lê N registros, filtra, grava no CSV temporário e descarta o lote, trocando o arquivo final no fim, como hoje. Com JSON em lista isso exige um parser incremental (como o `ijson`) ou que a origem envie JSON Lines, um registro por linha.
- **Log:** a maior parte do tempo foi o log de cada registro ignorado (7 dos 11 s). Nesse porte eu agruparia os ignorados por motivo ou os gravaria em um arquivo de rejeitados.
- **Paralelismo:** não compensa, porque o filtro leva menos de 2 s.

Se as regras de negócio crescerem, o próximo passo natural é separar o módulo em camadas (regras de domínio, casos de uso e adaptadores de entrada e saída). Hoje isso acrescentaria estrutura sem ganho.
