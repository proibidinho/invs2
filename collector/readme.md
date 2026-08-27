# collect_metrics.py — Guia para o time de Dashboard (Grafana/Splunk)

Este documento explica **como rodar o coletor** e **qual campo do
`dashboard_data.json` usar em cada painel**. Não é preciso entender Python
para usar este guia — só o caminho dos campos no JSON.

---

## 1. O que o script faz

O `collect_metrics.py` se conecta no AAP Controller, coleta os jobs (execuções
de automação), calcula as métricas e gera **um único arquivo**:

```
saida/dashboard_data.json
```

Esse é o **único arquivo que o dashboard precisa ler**. Todo o resto
(`history/jobs.json`, `history/job_host_summaries.json`) é uso interno do
script, para ele lembrar o que já coletou — o dashboard nunca precisa abrir
esses arquivos.

---

## 2. Como rodar

### 2.1. Primeira execução (carga histórica inicial)

Na primeira vez que o script roda em um ambiente novo (pasta `history/` ainda
não existe), ele automaticamente faz uma **carga inicial de até 730 dias**
(2 anos) para trás. Isso pode demorar bastante (são 2 anos de jobs), então
rode uma vez, manualmente, antes de agendar a execução diária:

```bash
python collect_metrics.py \
  --url https://aap.claro.com.br \
  --username SEU_USUARIO \
  --password SUA_SENHA \
  --history-dir ./history \
  --output-dir ./saida
```

Ou, se preferir usar variáveis de ambiente (arquivo `.env` na mesma pasta):

```
AAP_URL=https://aap.claro.com.br
AAP_USERNAME=SEU_USUARIO
AAP_PASSWORD=SUA_SENHA
AAP_HISTORY_DIR=./history
AAP_OUTPUT_DIR=./saida
```

e rodar só:

```bash
python collect_metrics.py
```

Ao final, vai existir:
- `history/jobs.json` e `history/job_host_summaries.json` → histórico bruto (não é para o dashboard ler)
- `saida/dashboard_data.json` → **é este arquivo que o Grafana/Splunk consome**

### 2.2. Execução diária (atualização incremental)

Depois da carga inicial, agende o **mesmo comando** para rodar 1x por dia
(cron, agendador do Windows, pipeline, o que for). O script detecta
sozinho que já existe histórico e busca só os jobs novos (mais uns dias de
sobreposição, para pegar jobs que ainda estavam em andamento na última
coleta). Não é preciso passar nenhum parâmetro diferente — é o **mesmo
comando** da carga inicial.

Exemplo de crontab (todo dia às 06:00):
```
0 6 * * * cd /caminho/do/script && python collect_metrics.py >> /var/log/aap_collect.log 2>&1
```

### 2.3. Uso manual/pontual (uma organização, sem tocar no histórico)

Se alguém quiser rodar uma consulta avulsa (ex.: conferir um número na mão),
sem mexer no histórico de produção:

```bash
python collect_metrics.py --org 98 --period 30d --no-history --output-dir ./teste
```

Isso gera um `dashboard_data.json` só daquela organização/período, em uma
pasta separada, sem tocar no histórico usado pela produção.

---

## 3. Onde o dashboard deve olhar

Tudo fica dentro de `saida/dashboard_data.json`, com esta forma:

```
dashboard_data.json
├── meta                              (informações da própria coleta)
├── organizations
│   ├── ALL                           (todas as organizações somadas)
│   │   ├── id / name
│   │   ├── periods
│   │   │   ├── 7d   → { summary, templates, top_30, curation }
│   │   │   ├── 14d  → { summary, templates, top_30, curation }
│   │   │   ├── 30d  → { summary, templates, top_30, curation }
│   │   │   ├── 3m   → { summary, templates, top_30, curation }
│   │   │   ├── 6m   → { summary, templates, top_30, curation }
│   │   │   ├── 1y   → { summary, templates, top_30, curation }
│   │   │   └── all  → { summary, templates, top_30, curation }
│   │   └── trend     (série diária: um ponto por dia, todo o histórico)
│   ├── 98                            (organização com id 98)
│   │   └── (mesma estrutura de ALL)
│   └── 99
│       └── (mesma estrutura de ALL)
└── platform_health
    ├── controller
    ├── execution_nodes
    ├── cluster_capacity_health_pct
    └── queue_pending_global
```

**Como o dashboard escolhe organização e período:** o Grafana deve ter duas
variáveis:
- `org` → lista as chaves de `organizations` (`ALL`, `98`, `99`, ...)
- `period` → lista as chaves de `periods` (`7d`, `14d`, `30d`, `3m`, `6m`, `1y`, `all`)

E monta o caminho: `organizations.<org>.periods.<period>.<campo que quiser>`.
Trocar de organização/período é só trocar essas duas variáveis — **não
precisa rodar o script de novo**, os dados de todas as combinações já estão
prontos no mesmo arquivo.

A única exceção é o `trend` (gráfico de linha de execuções x falhas): ele
fica em `organizations.<org>.trend`, **não dentro de `periods`**, porque já é
uma série diária completa — o próprio Grafana filtra o intervalo de datas
usando o time range do painel, sem precisar de uma cópia por período.

---

## 4. Mapa de campo → painel

Formato do exemplo: `caminho.no.json` → o que representa → onde usar.

### 4.1. Cards de resumo (KPIs)

| Painel | Caminho no JSON | Observação |
|---|---|---|
| Quantidade de execuções | `organizations.<org>.periods.<period>.summary.executions` | inteiro |
| Taxa de sucesso (%) | `organizations.<org>.periods.<period>.summary.success_rate` | já vem em percentual (ex.: `99.3`), **não** multiplicar por 100 |
| Quantidade de falhas | `organizations.<org>.periods.<period>.summary.failures` | inteiro |
| Duração média (segundos) | `organizations.<org>.periods.<period>.summary.avg_duration_seconds` | segundos |
| Hosts impactados | `organizations.<org>.periods.<period>.summary.hosts_impacted` | contagem de hosts **únicos** no período (não soma de execuções) |

> **Não existe** `summary.successful`. Se algum painel antigo usava
> `job.summary.successful` para "% de sucesso", troque para
> `organizations.<org>.periods.<period>.summary.success_rate` — já é o
> percentual pronto.

### 4.2. Tabela "Todos os Job Templates"

Fonte: `organizations.<org>.periods.<period>.templates` (lista, um item por
Job Template que teve execução no período).

| Coluna da tabela | Campo |
|---|---|
| ID do template | `template_id` |
| Nome (label) | `name` |
| Execuções | `executions` |
| Falhas | `failures` |
| % de sucesso | `success_rate` |
| Duração média (s) | `avg_duration_seconds` |
| Hosts impactados | `hosts_impacted` |

### 4.3. Top 30 automações mais executadas

Fonte: `organizations.<org>.periods.<period>.top_30` (mesmos campos da
tabela acima, mas só os 30 primeiros, ordenados por `executions` decrescente).

⚠️ Templates cujo nome comece com `escondida` já vêm **consolidados em um
único item** chamado `"Escondida* (consolidado)"`, com `template_id: null`
(porque representa vários templates somados). Isso só acontece no `top_30` —
na tabela completa (`templates`) e na curadoria, cada `escondida - job X`
continua separado.

### 4.4. Backlog / lista de curadoria

Fonte: `organizations.<org>.periods.<period>.curation`

```json
"curation": {
  "backlog_count": 3,
  "templates": [ ... ],
  "map": [ ... ]
}
```

| Painel | Campo |
|---|---|
| Número do backlog de curadoria (contador grande) | `curation.backlog_count` |
| Tabela de curadoria | `curation.templates` (mesmos campos de 4.2) |

Regra de negócio: entra na curadoria **todo** Job Template com
`success_rate < 90` (menor que 90%, inclui todos os templates, não só o
top 30). O Python só entrega os números — **a classificação por faixa de
gravidade (ex.: crítico/atenção/informativo) é o Grafana que decide**, com
base no próprio `success_rate`. Sugestão de faixas (defina como quiser no
painel):
- `success_rate < 70` → crítico
- `70 ≤ success_rate < 80` → grave
- `80 ≤ success_rate < 90` → atenção

### 4.5. Mapa de curadoria (scatter: execuções × falhas)

Fonte: `organizations.<org>.periods.<period>.curation.map`

| Eixo | Campo |
|---|---|
| Eixo X (volume) | `executions` |
| Eixo Y (falhas) | `failures` |
| Label do ponto | `name` (ou `template_id`) |
| Cor/tooltip extra | `success_rate` |

Contém **exatamente** os mesmos templates de `curation.templates` — não usa
o top 30 como origem. Não existe campo `impact` (ainda não foi definido o
que "impacto" significa para o negócio; quando for definido, o script pode
ser ajustado para incluir).

### 4.6. Tendência (gráfico de linha: execuções × falhas por dia)

Fonte: `organizations.<org>.trend` (fora de `periods`, é uma lista única).

```json
[
  { "date": "2026-08-20", "executions": 53, "failures": 1 },
  { "date": "2026-08-21", "executions": 82, "failures": 0 }
]
```

| Série do gráfico | Campo |
|---|---|
| Eixo X (tempo) | `date` |
| Linha "Execuções" | `executions` |
| Linha "Falhas" | `failures` |

### 4.7. Saúde da plataforma

Fonte: `platform_health` (não varia por organização nem por período — é do
cluster inteiro).

```json
"platform_health": {
  "controller": {
    "name": "10.29.6.53",
    "status": "ready",
    "capacity": 300,
    "consumed_capacity": 3,
    "percent_capacity_remaining": 99.0,
    "jobs_running": 0
  },
  "execution_nodes": [
    { "name": "10.29.6.54", "status": "ready", "capacity": 300,
      "consumed_capacity": 30, "percent_capacity_remaining": 90.0, "jobs_running": 1 }
  ],
  "cluster_capacity_health_pct": 92.25,
  "queue_pending_global": 0
}
```

| Painel | Campo | Observação |
|---|---|---|
| % de saúde do cluster (card único, resumo geral) | `platform_health.cluster_capacity_health_pct` | ver nota abaixo |
| Status do Controller | `platform_health.controller.status` | valor tipo `"ready"` |
| Capacidade do Controller | `platform_health.controller.capacity` / `.consumed_capacity` | |
| Tabela de Execution Nodes | `platform_health.execution_nodes[]` | um card/linha por nó |
| Jobs rodando por nó | `platform_health.execution_nodes[].jobs_running` | |
| Fila de jobs (pending+waiting) | `platform_health.queue_pending_global` | **é um número global do cluster inteiro**, não existe fila por Execution Node específico — a API do Controller não expõe isso por nó |

**Nota sobre `cluster_capacity_health_pct`:** não é a média simples dos
`percent_capacity_remaining` de cada nó. É calculado somando a `capacity` e
a `consumed_capacity` de **todos** os nós (Controller + Execution Nodes) e
tirando o percentual sobre o total somado:

```
cluster_capacity_health_pct = (soma(capacity) - soma(consumed_capacity)) / soma(capacity) * 100
```

Isso pondera corretamente nós com capacidades diferentes (um nó com o
dobro de capacidade pesa o dobro no resultado final) — uma média simples
dos percentuais trataria um nó pequeno e um nó grande como se tivessem o
mesmo peso, o que distorceria o número em clusters com nós heterogêneos.

---

## 5. Regras de negócio importantes (para não estranhar os números)

- **`success_rate` é sempre percentual** (`99.3`, não `0.993`). Nunca
  multiplicar por 100 de novo.
- **Só jobs terminados contam**: um job com status `running`, `pending`,
  `waiting`, `new` ou `canceled` **não** entra em nenhuma métrica
  (execuções, sucesso, falhas, duração, hosts, tendência). Como o coletor
  roda 1x por dia buscando o dia anterior, isso raramente aparece — é uma
  proteção para não contar um job que ainda não terminou.
- **`ALL` não é a média das organizações.** É recalculado a partir de
  todas as execuções somadas — `success_rate` de `ALL` é execuções
  bem-sucedidas totais / execuções totais, não a média dos `success_rate`
  de cada org. Da mesma forma, `hosts_impacted` de `ALL` é a união de
  hosts únicos de todas as organizações, não a soma dos `hosts_impacted`
  de cada uma (um host que aparece em duas organizações só conta uma vez).
- **`hosts_impacted` é sempre contagem de hosts únicos** no período —
  se um Job Template rodou 100 vezes só em `localhost`, `hosts_impacted`
  é **1**, não 100.
- **Templates "escondida"** só são consolidados no `top_30`. Na tabela
  completa (`templates`) e na curadoria, continuam separados.
- **Cada período (`7d`, `14d`, ...) é recalculado do zero** a partir dos
  jobs daquela janela — não é uma soma incremental de períodos menores.

---

## 6. Perguntas frequentes

**"Por que um Job Template não aparece em `hosts_impacted` com o número que eu esperava?"**
Só jobs do tipo `job` (execução de playbook) têm dados de host
(`job_host_summaries`). Jobs do tipo `project_update`, `inventory_update`,
`workflow_job` e `system_job` legitimamente não têm hosts — não é falta de
coleta, é o tipo de job que não roda contra hosts. Para saber se a cobertura
de dados de host está adequada, veja `meta.diagnostics.host_data_coverage_pct`
(calculado só sobre jobs do tipo `job`).

**"O arquivo `dashboard_data.json` está muito grande, dá para reduzir?"**
Ele cresce principalmente porque guarda `templates`/`top_30`/`curation` para
7 períodos × cada organização (necessário para o dashboard trocar de
período sem re-executar o coletor). Templates sem execução em um período
simplesmente não aparecem naquele período (não há linhas zeradas). Se o
tamanho virar um problema real de performance no Grafana, dá para reduzir o
número de períodos pré-calculados (ex.: tirar `14d` e `1y` se ninguém usar).

**"Posso rodar o script mais de uma vez no mesmo dia?"**
Sim, é seguro — ele sempre lê o histórico existente e só busca o que é novo
(mais um pequeno overlap de segurança). Rodar de novo no mesmo dia não
duplica nem corrompe dados.