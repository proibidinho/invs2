# README — Como consumir o `dashboard_data.json`

> Guia prático para o time responsável por construir o dashboard.
>
> O objetivo deste documento é evitar que seja necessário ler dezenas de milhares de linhas do JSON para descobrir onde estão os dados. As métricas principais já são entregues **calculadas e organizadas** pelo coletor. Na maior parte dos casos, o dashboard deve apenas selecionar a organização, selecionar o período e consumir o campo indicado neste README.

---

## 1. Regra mais importante

**Não recalcule no dashboard o que o JSON já entrega pronto.**

Por exemplo:

- Não conte jobs para descobrir o número de execuções.
- Não calcule manualmente a taxa de sucesso.
- Não some falhas para montar o total geral.
- Não calcule média das durações.
- Não tente reconstruir `hosts_impacted`.
- Não refaça o Top 30.
- Não refaça o backlog de curadoria.

O coletor já fez esses cálculos.

Para quase todos os indicadores, o fluxo é:

```text
organizations
  -> organização escolhida
      -> periods
          -> período escolhido
              -> campo desejado
```

Exemplo:

```text
organizations.ALL.periods.30d.summary.executions
```

Significa:

```text
organizations
└── ALL
    └── periods
        └── 30d
            └── summary
                └── executions
```

---

# 2. Visão geral da estrutura do JSON

A estrutura de alto nível é esta:

```json
{
  "meta": {
    "...": "..."
  },
  "organizations": {
    "ALL": {
      "id": null,
      "name": "ALL",
      "periods": {
        "7d": {},
        "14d": {},
        "30d": {},
        "3m": {},
        "6m": {},
        "1y": {},
        "all": {}
      },
      "trend": []
    },

    "<ID_DA_ORGANIZACAO>": {
      "id": 123,
      "name": "Nome da organização",
      "periods": {},
      "trend": []
    }
  },
  "platform_health": {
    "...": "..."
  }
}
```

Existem três blocos principais:

| Bloco | Para que serve |
|---|---|
| `meta` | Metadados da coleta e diagnóstico da qualidade dos dados |
| `organizations` | Métricas de jobs/templates, separadas por organização e período |
| `platform_health` | Saúde atual do Controller e Execution Nodes |

---

# 3. Organização e período: os dois filtros principais

## 3.1 Organização

Todas as métricas operacionais ficam dentro de:

```text
organizations
```

Existe uma organização especial:

```text
organizations.ALL
```

`ALL` representa a visão agregada de todas as organizações.

Portanto, se o usuário selecionar no dashboard:

```text
Organização = Todas
```

o dashboard deve consumir:

```text
organizations.ALL
```

Para uma organização específica, o JSON utiliza a chave daquela organização e também informa:

```json
{
  "id": 123,
  "name": "Nome da organização"
}
```

### Sugestão para montar o dropdown de organizações

Percorrer:

```text
organizations
```

e usar:

```text
organizations.<org>.name
```

como texto exibido ao usuário.

A chave `ALL` deve aparecer como opção de visão geral.

---

## 3.2 Período

Cada organização possui períodos já calculados:

```text
organizations.<org>.periods
```

Os períodos possíveis são:

| Chave | Significado |
|---|---|
| `7d` | últimos 7 dias disponíveis |
| `14d` | últimos 14 dias |
| `30d` | últimos 30 dias |
| `3m` | aproximadamente 90 dias |
| `6m` | aproximadamente 180 dias |
| `1y` | aproximadamente 365 dias |
| `all` | todo o histórico disponível dentro da retenção |

Exemplo:

```text
organizations.ALL.periods.7d
```

ou:

```text
organizations.<org>.periods.30d
```

### IMPORTANTE

O dashboard **não precisa recalcular os períodos**.

Cada período já contém:

```text
summary
templates
top_30
curation
```

prontos.

---

# 4. Cards principais do dashboard

Os indicadores gerais ficam em:

```text
organizations.<org>.periods.<period>.summary
```

Estrutura:

```json
"summary": {
  "executions": 30710,
  "failures": 4146,
  "success_rate": 86.5,
  "avg_duration_seconds": 22.4,
  "hosts_impacted": 128
}
```

---

## 4.1 Número de execuções

### Campo

```text
organizations.<org>.periods.<period>.summary.executions
```

### Exemplo — todas as organizações / 7 dias

```text
organizations.ALL.periods.7d.summary.executions
```

No arquivo analisado:

```text
30710
```

### O que significa

Quantidade total de execuções consideradas nas métricas daquele período.

O coletor já remove dos agregados jobs que ainda não estão em estado terminal.

---

## 4.2 Quantidade de falhas

### Campo

```text
organizations.<org>.periods.<period>.summary.failures
```

Exemplo:

```text
organizations.ALL.periods.7d.summary.failures
```

Valor encontrado na amostra:

```text
4146
```

As falhas correspondem aos status:

```text
failed
error
```

Não é necessário o dashboard fazer essa contagem.

---

## 4.3 Taxa de sucesso

### Campo

```text
organizations.<org>.periods.<period>.summary.success_rate
```

Exemplo:

```text
organizations.ALL.periods.7d.summary.success_rate
```

Valor:

```text
86.5
```

### IMPORTANTE

O valor **já está em percentual de 0 a 100**.

Portanto:

```text
86.5
```

significa:

```text
86,5%
```

### NÃO fazer

```text
86.5 * 100
```

Isso produziria um valor incorreto.

No dashboard basta formatar o número adicionando `%`.

---

## 4.4 Duração média das execuções

### Campo

```text
organizations.<org>.periods.<period>.summary.avg_duration_seconds
```

Exemplo:

```text
organizations.ALL.periods.7d.summary.avg_duration_seconds
```

Valor:

```text
22.4
```

Unidade:

```text
segundos
```

O dashboard pode apenas converter a apresentação, se desejado.

Exemplo:

```text
22.4 segundos
```

ou, para durações maiores:

```text
3661 segundos -> 1h 1m 1s
```

Mas o valor-base deve continuar sendo o entregue pelo JSON.

---

## 4.5 Hosts impactados

### Campo

```text
organizations.<org>.periods.<period>.summary.hosts_impacted
```

Exemplo:

```text
organizations.ALL.periods.7d.summary.hosts_impacted
```

Valor da amostra:

```text
128
```

### O que significa

Quantidade de **hosts únicos** impactados pelas execuções daquele recorte.

### IMPORTANTE

Não somar `hosts_impacted` dos templates para tentar obter o total.

O mesmo host pode aparecer em vários templates.

O coletor calcula a união de hosts corretamente antes de gerar este campo.

Portanto, para o card geral, consumir diretamente:

```text
summary.hosts_impacted
```

---

# 5. Tabela completa de Job Templates

Se for necessário exibir todos os Job Templates do período, usar:

```text
organizations.<org>.periods.<period>.templates
```

Esse campo é uma lista.

Cada item possui:

```json
{
  "template_id": 420,
  "name": "Monitoração | SPG | Recovery",
  "executions": 926,
  "failures": 0,
  "success_rate": 100.0,
  "avg_duration_seconds": 8.1,
  "hosts_impacted": 1
}
```

## Campos disponíveis por template

| Campo | Significado |
|---|---|
| `template_id` | ID do Job Template |
| `name` | Nome do Job Template |
| `executions` | Quantidade de execuções daquele template |
| `failures` | Quantidade de falhas |
| `success_rate` | Taxa de sucesso em percentual |
| `avg_duration_seconds` | Duração média em segundos |
| `hosts_impacted` | Quantidade de hosts únicos impactados |

### Exemplo de caminho

```text
organizations.ALL.periods.30d.templates
```

Depois basta iterar sobre a lista.

---

# 6. Top 30 Job Templates

## Onde está

```text
organizations.<org>.periods.<period>.top_30
```

Exemplo:

```text
organizations.ALL.periods.30d.top_30
```

O resultado já vem limitado aos 30 templates/grupos com mais execuções.

### NÃO é necessário

- ordenar novamente para descobrir o Top 30;
- contar execuções;
- cortar manualmente os primeiros 30 a partir de `templates`.

O coletor já faz isso.

Cada item contém:

```json
{
  "template_id": 749,
  "name": "Devolve SH pro Splunk",
  "executions": 6548,
  "failures": 6,
  "success_rate": 99.9,
  "avg_duration_seconds": 5.4,
  "hosts_impacted": 1
}
```

---

## 6.1 Regra especial: `Escondida*`

Todos os templates cujo nome começa com:

```text
Escondida
```

são consolidados **somente na visão Top 30** em um grupo chamado:

```text
Escondida* (consolidado)
```

Esse grupo pode aparecer assim:

```json
{
  "template_id": null,
  "name": "Escondida* (consolidado)",
  "executions": 10549,
  "failures": 1852,
  "success_rate": 82.4,
  "avg_duration_seconds": 31.6,
  "hosts_impacted": 2
}
```

### IMPORTANTE

Para esse registro:

```text
template_id = null
```

é **esperado**.

Não tratar como erro de parsing ou dado faltante.

O `null` significa que aquela linha representa vários templates consolidados e, portanto, não existe um único `template_id`.

---

# 7. Backlog de curadoria

O backlog serve para mostrar Job Templates do Top 30 que precisam de atenção.

## Onde está

```text
organizations.<org>.periods.<period>.curation
```

Estrutura:

```json
"curation": {
  "backlog_count": 13,
  "templates": [],
  "map": []
}
```

---

## 7.1 Número de itens no backlog

Para um card como:

```text
Templates em curadoria
```

usar diretamente:

```text
organizations.<org>.periods.<period>.curation.backlog_count
```

Exemplo:

```text
organizations.ALL.periods.all.curation.backlog_count
```

Não é necessário contar o tamanho de `templates`, embora em condições normais o resultado corresponda à lista.

---

## 7.2 Quais templates estão no backlog

Usar:

```text
organizations.<org>.periods.<period>.curation.templates
```

Cada item possui:

```text
template_id
name
executions
failures
success_rate
avg_duration_seconds
hosts_impacted
```

### Regra da curadoria implementada no coletor

Entram no backlog somente itens que:

```text
estão no Top 30 por número de execuções
E
success_rate < 90
```

Portanto:

```text
success_rate = 89.9 -> entra
success_rate = 90.0 -> não entra
success_rate = 95.0 -> não entra
```

Um template com taxa de sucesso baixa, mas que esteja fora do Top 30, **não entra** no backlog.

### Ordenação

A lista de curadoria é ordenada pela menor taxa de sucesso primeiro.

Ou seja, os piores resultados aparecem antes.

---

## 7.3 Atenção: `Escondida*` também pode aparecer na curadoria

O comportamento efetivo do script é:

```text
top_30
   -> filtro success_rate < 90
       -> curation
```

Por isso, se:

```text
Escondida* (consolidado)
```

estiver no Top 30 e possuir taxa de sucesso inferior a 90%, ele também pode aparecer em:

```text
curation.templates
```

e:

```text
curation.map
```

Nesse caso:

```text
template_id = null
```

é válido.

---

# 8. Mapa de curadoria

Para construir o gráfico/mapa de curadoria, utilizar:

```text
organizations.<org>.periods.<period>.curation.map
```

Cada item possui apenas:

```json
{
  "template_id": 2653,
  "name": "Consulta-Perfil-E-Comercializacao-De-Produto",
  "executions": 3,
  "failures": 2,
  "success_rate": 33.3
}
```

## Campos recomendados para o gráfico

O coletor foi desenhado para um mapa usando:

```text
Eixo X = executions
Eixo Y = failures
```

Informações adicionais para tooltip/label:

```text
name
success_rate
template_id
```

### IMPORTANTE

Não procurar os campos:

```text
impact
severity
failure_rate
successful
```

Eles não fazem parte do modelo final utilizado pelo dashboard.

Não inventar um cálculo de `impact`.

---

# 9. Tendência de execuções e falhas

A tendência diária fica em:

```text
organizations.<org>.trend
```

### IMPORTANTE

`trend` **não fica dentro de `periods`**.

Errado:

```text
organizations.ALL.periods.30d.trend
```

Correto:

```text
organizations.ALL.trend
```

Estrutura:

```json
[
  {
    "date": "2026-08-11",
    "executions": 2,
    "failures": 0
  },
  {
    "date": "2026-08-12",
    "executions": 4,
    "failures": 3
  }
]
```

Cada ponto possui:

| Campo | Uso |
|---|---|
| `date` | Eixo de tempo |
| `executions` | Quantidade de execuções naquele dia |
| `failures` | Quantidade de falhas naquele dia |

## Uso sugerido

Gráfico temporal com duas séries:

```text
Execuções
Falhas
```

### Por que `trend` não possui `7d`, `30d`, etc.?

A série é gerada uma única vez para todo o histórico da organização.

O dashboard pode filtrar as datas exibidas conforme o período desejado.

Isso evita duplicar a série diária sete vezes no JSON.

---

# 10. Saúde da plataforma

A saúde da plataforma é **global**.

Ela não fica dentro de:

```text
organizations
```

O caminho é:

```text
platform_health
```

Estrutura:

```json
{
  "controller": {},
  "execution_nodes": [],
  "cluster_capacity_health_pct": 99.49,
  "queue_pending_global": 0
}
```

---

# 11. Controller

## Caminho

```text
platform_health.controller
```

Exemplo real da run analisada:

```json
{
  "name": "10.29.6.53",
  "status": "ready",
  "capacity": 297,
  "consumed_capacity": 2,
  "percent_capacity_remaining": 99.33,
  "jobs_running": 0
}
```

Campos:

| Campo | Significado |
|---|---|
| `name` | Nome/hostname do nó |
| `status` | Estado retornado pelo Controller |
| `capacity` | Capacidade total do nó |
| `consumed_capacity` | Capacidade atualmente consumida |
| `percent_capacity_remaining` | Percentual de capacidade restante |
| `jobs_running` | Jobs rodando naquele nó |

Para mostrar a saúde individual do Controller, o campo mais direto é:

```text
platform_health.controller.percent_capacity_remaining
```

Para mostrar o status:

```text
platform_health.controller.status
```

---

# 12. Execution Nodes

## Caminho

```text
platform_health.execution_nodes
```

É uma lista.

Exemplo:

```json
[
  {
    "name": "10.53.9.92",
    "status": "ready",
    "capacity": 297,
    "consumed_capacity": 0,
    "percent_capacity_remaining": 100.0,
    "jobs_running": 0
  }
]
```

O dashboard deve iterar sobre essa lista para criar uma linha/card por Execution Node.

Campos disponíveis são os mesmos do Controller:

```text
name
status
capacity
consumed_capacity
percent_capacity_remaining
jobs_running
```

---

# 13. Saúde geral de capacidade do cluster

Para o indicador geral de saúde/capacidade da plataforma, usar:

```text
platform_health.cluster_capacity_health_pct
```

Na run analisada:

```text
99.49
```

Isso significa:

```text
99,49%
```

### IMPORTANTE

Não fazer a média de:

```text
controller.percent_capacity_remaining
execution_nodes[*].percent_capacity_remaining
```

O coletor já calcula corretamente a saúde do cluster considerando a capacidade de todos os nós.

Portanto consumir diretamente:

```text
cluster_capacity_health_pct
```

---

# 14. Fila global

## Campo

```text
platform_health.queue_pending_global
```

Na amostra:

```text
0
```

Esse número representa a contagem global de jobs:

```text
pending + waiting
```

no cluster.

### IMPORTANTE

A API utilizada pelo coletor não fornece essa fila separada por Execution Node.

Portanto **não criar** campos como:

```text
execution_node.queue
```

ou tentar derivar fila a partir de:

```text
consumed_capacity
jobs_running
```

`consumed_capacity` não é tamanho de fila.

---

# 15. Metadados da coleta

Os metadados ficam em:

```text
meta
```

Exemplo da run analisada:

```json
{
  "generated_at": "2026-08-30T19:42:43.951040+00:00",
  "mode": "carga_inicial",
  "history_start": "2026-02-24",
  "history_end": "2026-08-29",
  "max_history_days": 730,
  "periods": [
    "7d",
    "14d",
    "30d",
    "3m",
    "6m",
    "1y",
    "all"
  ]
}
```

---

## 15.1 Quando o arquivo foi gerado

```text
meta.generated_at
```

Pode ser usado para mostrar algo como:

```text
Última atualização dos dados
```

---

## 15.2 Início e fim reais do histórico disponível

```text
meta.history_start
meta.history_end
```

Na run analisada:

```text
history_start = 2026-02-24
history_end   = 2026-08-29
```

Esses campos são a referência correta para saber o intervalo realmente presente no arquivo.

---

## 15.3 `max_history_days` NÃO significa quantidade de dias existentes no arquivo

Campo:

```text
meta.max_history_days
```

Na run:

```text
730
```

Isso significa:

```text
o coletor pode reter até 730 dias
```

Não significa necessariamente:

```text
existem 730 dias coletados neste JSON
```

Na run analisada, apesar de:

```text
max_history_days = 730
```

o histórico efetivamente encontrado vai de:

```text
2026-02-24
```

até:

```text
2026-08-29
```

Portanto o dashboard não deve mostrar:

```text
"730 dias de dados"
```

apenas porque `max_history_days` vale 730.

Se quiser mostrar o intervalo real, usar:

```text
history_start
history_end
```

---

# 16. Diagnóstico de cobertura dos dados de host

Caminho:

```text
meta.diagnostics
```

Estrutura:

```json
{
  "eligible_job_type_executions": 673568,
  "eligible_with_host_data": 673568,
  "host_data_coverage_pct": 100.0
}
```

Campos:

| Campo | Significado |
|---|---|
| `eligible_job_type_executions` | Execuções para as quais informação de host é aplicável |
| `eligible_with_host_data` | Quantas dessas possuem dados de host |
| `host_data_coverage_pct` | Percentual de cobertura |

Na run analisada:

```text
host_data_coverage_pct = 100.0
```

Esse campo é principalmente um indicador de qualidade da coleta.

Se o dashboard possuir um card de qualidade/cobertura dos dados, consumir:

```text
meta.diagnostics.host_data_coverage_pct
```

---

# 17. Resumo: qual campo usar para cada painel

| Informação desejada | Caminho |
|---|---|
| Número de execuções | `organizations.<org>.periods.<period>.summary.executions` |
| Quantidade de falhas | `organizations.<org>.periods.<period>.summary.failures` |
| Taxa de sucesso | `organizations.<org>.periods.<period>.summary.success_rate` |
| Duração média | `organizations.<org>.periods.<period>.summary.avg_duration_seconds` |
| Hosts impactados | `organizations.<org>.periods.<period>.summary.hosts_impacted` |
| Todos os templates | `organizations.<org>.periods.<period>.templates` |
| Top 30 | `organizations.<org>.periods.<period>.top_30` |
| Quantidade em curadoria | `organizations.<org>.periods.<period>.curation.backlog_count` |
| Lista da curadoria | `organizations.<org>.periods.<period>.curation.templates` |
| Mapa de curadoria | `organizations.<org>.periods.<period>.curation.map` |
| Tendência diária | `organizations.<org>.trend` |
| Saúde geral do cluster | `platform_health.cluster_capacity_health_pct` |
| Fila global | `platform_health.queue_pending_global` |
| Controller | `platform_health.controller` |
| Execution Nodes | `platform_health.execution_nodes` |
| Cobertura de hosts | `meta.diagnostics.host_data_coverage_pct` |
| Data da geração | `meta.generated_at` |
| Início real do histórico | `meta.history_start` |
| Fim real do histórico | `meta.history_end` |

---

# 18. Exemplo completo de consumo

Suponha que o usuário escolha:

```text
Organização = ALL
Período = 7d
```

A raiz do recorte passa a ser:

```text
organizations.ALL.periods.7d
```

A partir dela:

```text
Card "Execuções"
-> organizations.ALL.periods.7d.summary.executions

Card "Falhas"
-> organizations.ALL.periods.7d.summary.failures

Card "Taxa de sucesso"
-> organizations.ALL.periods.7d.summary.success_rate

Card "Duração média"
-> organizations.ALL.periods.7d.summary.avg_duration_seconds

Card "Hosts impactados"
-> organizations.ALL.periods.7d.summary.hosts_impacted

Tabela "Top 30"
-> organizations.ALL.periods.7d.top_30

Card "Backlog de curadoria"
-> organizations.ALL.periods.7d.curation.backlog_count

Tabela "Curadoria"
-> organizations.ALL.periods.7d.curation.templates

Gráfico "Mapa de curadoria"
-> organizations.ALL.periods.7d.curation.map
```

A tendência é uma exceção:

```text
Gráfico "Tendência"
-> organizations.ALL.trend
```

A saúde da plataforma também é independente da organização e do período:

```text
Saúde do cluster
-> platform_health.cluster_capacity_health_pct

Fila
-> platform_health.queue_pending_global

Controller
-> platform_health.controller

Execution Nodes
-> platform_health.execution_nodes
```

---

# 19. Pseudocódigo simples para o front-end

Exemplo conceitual em JavaScript:

```javascript
const selectedOrg = "ALL";
const selectedPeriod = "30d";

const org = data.organizations[selectedOrg];
const period = org.periods[selectedPeriod];

const executions = period.summary.executions;
const failures = period.summary.failures;
const successRate = period.summary.success_rate;
const avgDuration = period.summary.avg_duration_seconds;
const hostsImpacted = period.summary.hosts_impacted;

const templates = period.templates;
const top30 = period.top_30;

const curationCount = period.curation.backlog_count;
const curationTemplates = period.curation.templates;
const curationMap = period.curation.map;

// Trend NÃO fica dentro de periods
const trend = org.trend;

// Saúde é global
const platformHealth = data.platform_health;
```

---

# 20. O que NÃO deve ser feito no dashboard

Evitar estas implementações:

```text
❌ Ler todos os templates e somar executions para criar o card geral
❌ Calcular success_rate = sucessos / execuções
❌ Calcular failures a partir de success_rate
❌ Somar hosts_impacted entre templates
❌ Montar o Top 30 novamente
❌ Filtrar todos os templates com success_rate < 90 para montar curadoria
❌ Criar curadoria com templates fora do Top 30
❌ Inventar impact, severity ou failure_rate
❌ Multiplicar success_rate por 100
❌ Calcular saúde do cluster como média simples dos percentuais dos nós
❌ Inventar fila por Execution Node
❌ Procurar trend dentro de periods
❌ Considerar template_id = null do grupo Escondida como erro
```

O JSON final foi criado justamente para que essas regras fiquem centralizadas no coletor.

---

# 21. Regras de negócio importantes

## Jobs considerados nas métricas

Entram nos agregados somente jobs com status terminal:

```text
successful
failed
error
```

Não entram enquanto estiverem em:

```text
running
pending
waiting
new
canceled
```

O dashboard não precisa repetir esse filtro, porque os números já chegam calculados.

---

## Falhas

São consideradas falhas:

```text
failed
error
```

---

## Taxa de sucesso

Já chega como percentual:

```text
0.0 até 100.0
```

---

## Curadoria

Regra efetiva:

```text
Top 30 por execuções
+
success_rate < 90%
```

---

## Top 30

Ordenado por quantidade de execuções.

Templates iniciados por `Escondida` são consolidados em:

```text
Escondida* (consolidado)
```

---

## Hosts impactados

São hosts únicos, e não soma do número de hosts de cada execução.

---

# 22. Tratamento de valores nulos e listas vazias

O front-end deve tolerar:

```text
null
[]
0
0.0
```

Exemplo legítimo:

```text
template_id = null
```

para:

```text
Escondida* (consolidado)
```

Se não houver itens em uma curadoria:

```json
{
  "backlog_count": 0,
  "templates": [],
  "map": []
}
```

Isso deve ser mostrado como ausência de backlog, e não como erro.

---

# 23. Sugestão de componentes do dashboard

Uma estrutura simples pode ser:

```text
[Filtros]
- Organização
- Período

[Cards]
- Execuções
- Falhas
- Taxa de sucesso
- Duração média
- Hosts impactados
- Itens no backlog de curadoria

[Gráficos / tabelas]
- Tendência de execuções x falhas
- Top 30 de Job Templates
- Backlog de curadoria
- Mapa de curadoria

[Saúde da plataforma]
- Saúde geral do cluster
- Fila global
- Controller
- Execution Nodes
```

---

# 24. Checklist para validar a integração

Antes de considerar o dashboard pronto, validar:

- [ ] O dropdown de organização consegue selecionar `ALL` e organizações específicas.
- [ ] O dropdown de período usa `7d`, `14d`, `30d`, `3m`, `6m`, `1y` e `all`.
- [ ] Execuções vêm de `summary.executions`.
- [ ] Falhas vêm de `summary.failures`.
- [ ] Taxa de sucesso vem diretamente de `summary.success_rate`.
- [ ] A taxa não está sendo multiplicada por 100.
- [ ] Duração média usa `summary.avg_duration_seconds`.
- [ ] Hosts impactados usam `summary.hosts_impacted`.
- [ ] O Top 30 usa diretamente `top_30`.
- [ ] A curadoria usa diretamente `curation`.
- [ ] Apenas os itens fornecidos em `curation.templates` são tratados como backlog.
- [ ] O mapa usa `curation.map`.
- [ ] O mapa usa `executions` no eixo X e `failures` no eixo Y.
- [ ] `trend` é lido em `organizations.<org>.trend`.
- [ ] Saúde é lida em `platform_health`.
- [ ] A fila é global e usa `queue_pending_global`.
- [ ] O front aceita `template_id = null` no grupo `Escondida* (consolidado)`.
- [ ] O histórico real é exibido usando `history_start` e `history_end`, se necessário.
- [ ] `max_history_days` não é apresentado como se fosse o número real de dias coletados.

---

# 25. Regra prática final

Se o time precisar de um número para um card e estiver pensando:

```text
"vamos calcular isso a partir do restante do JSON"
```

primeiro verificar este README.

A filosofia do arquivo é:

```text
COLETOR = coleta + aplica regras + calcula métricas
DASHBOARD = seleciona + exibe
```

Ou seja, o dashboard deve ser o mais simples possível e consumir os campos já preparados pelo coletor.
