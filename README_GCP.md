# integration_assets_gcp

Sincronização de inventário **Google Cloud Platform (GCP)** (via Ansible
Automation Platform) para **Jira Assets / CMDB**.

Este projeto segue o mesmo modelo das integrações Azure e AWS e utiliza
o inventário já coletado pelo **Ansible Automation Platform (AAP)** como
fonte de dados para cadastro dos ativos no CMDB.

------------------------------------------------------------------------

# ⚠️ Escopo Atual do Projeto

Embora a arquitetura já possua componentes para operações de **Create**,
**Update** e **Deactivate**, atualmente o projeto encontra-se homologado
e aprovado apenas para **criação de novos ativos** no CMDB.

Neste momento:

-   ✅ Create: suportado e utilizado.
-   ⚠️ Update: previsto para desenvolvimento futuro.
-   ⚠️ Deactivate: previsto para desenvolvimento futuro.

O comportamento atual é:

``` text
Servidor existe no GCP e não existe no CMDB
    → CREATE

Servidor existe no GCP e já existe no CMDB
    → SKIP

Servidor não existe mais no GCP
    → Nenhuma ação
```

A estratégia adotada nesta primeira fase visa evitar alterações
automáticas ou desativações indevidas enquanto as regras de governança e
ownership dos ativos são consolidadas.

------------------------------------------------------------------------

## Arquitetura

``` text
Google Cloud Platform
        │
        ▼
Inventory Source GCP
(Ansible Automation Platform)
        │
        ▼
AAP API
(hosts + variables)
        │
        ▼
gcp_cmdb_filters.py
        │
        ▼
cloud_data
        │
        ▼
Payload Jira Assets
        │
        ▼
POST /object/create
        │
        ▼
Jira Assets / CMDB
```

------------------------------------------------------------------------

## Estrutura de arquivos

``` text
playbooks/
├── setup_webhook.yml
├── sync_gcp_cmdb.yml
└── sync_single_gcp.yml

roles/
└── integration_assets_gcp/
    ├── filter_plugins/
    │   └── gcp_cmdb_filters.py
    ├── tasks/
    │   ├── main.yml
    │   ├── create.yml
    │   ├── deactivate.yml
    │   └── manage_network_interface.yml
    └── vars/
        ├── main.yml
        ├── mapeamento_gcp_cmdb.yml
        └── modelo_servidor_map_gcp.yml

scripts/
└── discover_attribute_ids.py

README.md
```

------------------------------------------------------------------------

# Arquitetura Funcional

``` text
AAP Inventory GCP
       │
       ▼
Buscar Hosts
       │
       ▼
batch_transform_gcp_hosts()
       │
       ▼
cloud_data
       │
       ▼
Comparação com CMDB
       │
       ├────────► Create
       │
       └────────► Skip
```

------------------------------------------------------------------------

## Fonte dos Dados

O projeto não consulta diretamente o GCP durante o processo normal de
sincronização.

Toda a coleta é realizada através da API do próprio AAP:

``` http
GET /api/controller/v2/inventories/{inventory_id}/hosts/
```

e

O inventário GCP do AAP já fornece todas as informações necessárias:

-   name
-   project
-   zone
-   machine_type
-   labels
-   status
-   disks
-   networkInterfaces
-   cpuPlatform
-   id

Dessa forma foram eliminadas dependências de chamadas como:

``` bash
gcloud compute instances list
gcloud compute instances describe
gcloud compute machine-types describe
```

durante o sync.

------------------------------------------------------------------------

# Playbooks

## sync_gcp_cmdb.yml

Playbook principal responsável pela sincronização entre:

``` text
AAP
  ↓
Jira Assets
```

### Execução

``` bash
ansible-playbook playbooks/sync_gcp_cmdb.yml \
  -e "sync_mode=full"
```

------------------------------------------------------------------------

## sync_single_gcp.yml

Playbook utilizado para testes e homologação.

Permite executar a sincronização somente para alguns servidores.

### Por lista

``` bash
ansible-playbook playbooks/sync_single_gcp.yml \
  -e 'test_servers=["srv01","srv02"]'
```

### Por limite

``` bash
ansible-playbook playbooks/sync_single_gcp.yml \
  -e "test_limit=5"
```

### Dry Run

``` bash
ansible-playbook playbooks/sync_single_gcp.yml \
  -e "test_limit=5" \
  -e "dry_run=true"
```

Neste modo nenhum objeto é criado no CMDB.

O playbook exibe somente o conteúdo transformado do objeto `cloud_data`.

------------------------------------------------------------------------

## setup_webhook.yml

Playbook opcional utilizado para habilitar sincronização baseada em
eventos do GCP.

Fluxo:

``` text
Compute Engine
      │
      ▼
Cloud Logging
      │
      ▼
Log Sink
      │
      ▼
Pub/Sub
      │
      ▼
Cloud Function
      │
      ▼
AAP
```

------------------------------------------------------------------------

### APIs habilitadas

``` text
pubsub.googleapis.com

cloudfunctions.googleapis.com

cloudbuild.googleapis.com
```

------------------------------------------------------------------------

### Eventos monitorados

``` text
compute.instances.insert
compute.instances.delete
compute.instances.start
compute.instances.stop
```

------------------------------------------------------------------------

### Objetivo

Quando um evento é gerado no Compute Engine:

``` text
Compute Engine
      ▼
Pub/Sub
      ▼
Cloud Function
      ▼
AAP Job Template
      ▼
CMDB
```

Isso reduz a necessidade de sincronizações agendadas.

------------------------------------------------------------------------

# Funcionamento da Role

A role principal é composta por cinco fases.

------------------------------------------------------------------------

## Fase 1 --- Coleta dos Hosts

Busca todos os hosts do inventário GCP do AAP.

``` text
Inventory ID = 91
```

Posteriormente coleta o:

``` text
variable_data
```

de cada host.

------------------------------------------------------------------------

## Fase 2 --- Transformação

Executa o filter plugin:

``` python
transform_gcp_host()
```

ou

``` python
batch_transform_gcp_hosts()
```

convertendo o formato do inventário AAP para o padrão interno:

``` text
cloud_data
```

utilizado pelo Jira Assets.

------------------------------------------------------------------------

## Fase 3 --- Comparação

Consulta o CMDB:

``` aql
objectTypeId = 121
AND Datacenter = "Google Cloud"
```

e separa os ativos em:

``` text
servers_to_create
servers_to_skip
servers_to_deactivate
```

------------------------------------------------------------------------

## Fase 4 --- Sincronização

Atualmente apenas a operação de Create é utilizada.

### Create

Servidor encontrado no inventário do AAP mas inexistente no CMDB.

``` http
POST /object/create
```

------------------------------------------------------------------------

### Skip

Servidor já existente no CMDB.

Nenhuma alteração é realizada.

Isso preserva qualquer ajuste manual realizado pelas equipes
responsáveis.

------------------------------------------------------------------------

### Update (futuro)

Já previsto arquiteturalmente.

Funcionalidade ainda não utilizada.

Possíveis atributos:

-   CPU
-   Memória
-   Sistema Operacional
-   Ambiente
-   Network Interfaces
-   Owner
-   Modelo de Servidor

------------------------------------------------------------------------

### Deactivate (futuro)

Já existem componentes preparados para suportar desativação.

Entretanto o processo está desabilitado.

Fluxo previsto:

``` text
Servidor removido do GCP
        ▼
Existe apenas no CMDB
        ▼
Status = Desativado
```

------------------------------------------------------------------------

## Fase 5 --- Relatório Final

Ao término do processamento são exibidas estatísticas:

``` text
Criados
Existentes (Skip)
Desativados
Erros
```

------------------------------------------------------------------------

# Filter Plugin

Arquivo:

``` text
roles/integration_assets_gcp/filter_plugins/gcp_cmdb_filters.py
```

Responsável pela transformação dos dados.

------------------------------------------------------------------------

## transform_gcp_host()

Transforma um host individual do AAP em um objeto `cloud_data`.

``` text
Host AAP
      ▼
cloud_data
```

------------------------------------------------------------------------

## batch_transform_gcp_hosts()

Processa todos os hosts em lote.

``` text
Lista de hosts
      ▼
Lista de cloud_data
```

------------------------------------------------------------------------

## update_asset_gcp()

Transforma o objeto `cloud_data` em payload compatível com Jira Assets.

``` text
cloud_data
      ▼
JSON Assets
```

------------------------------------------------------------------------

# Regras de Exclusão

O filtro ignora automaticamente:

### Hosts desabilitados

``` yaml
enabled: false
```

### Nós GKE

Detectados através de labels:

``` text
goog-gke-*
goog-k8s-*
```

### Hosts sem sistema CMDB

Quando a label obrigatória não existe:

``` text
ef_cmdb
```

------------------------------------------------------------------------

# Campos Populados no CMDB

  Atributo              Origem
  --------------------- ------------------------------------
  Name                  host.name
  FQDN                  name.zone.c.project.internal
  Conta Cloud           Projeto GCP
  Sistema               label ef_cmdb
  Ambiente              labels
  Modelo do Servidor    machine_type
  CPU Count             gcp_machine_specs
  Memória RAM           gcp_machine_specs
  Sistema Operacional   disks\[\].licenses
  Interface de Rede     networkInterfaces
  Status                status GCP
  Datacenter            Google Cloud
  Tipo Infraestrutura   CLOUD PUBLICA
  Fornecedor            Google Cloud
  Owner                 owner_ids
  CPU Platform          cpu_platform_map
  Capacidade do Disco   diskSizeGb
  Disaster Recovery     ef_dr / ef_recuperacao_de_desastre

------------------------------------------------------------------------

# Modelo do Servidor

Os modelos GCP são convertidos para os objetos cadastrados no CMDB.

Fluxo:

``` text
machine_type
      ▼
modelo_servidor_map
      ▼
GDA-XXXXXXX
```

Exemplo:

``` yaml
e2-standard-4: GDA-3223941
n1-standard-2: GDA-3223792
c2-standard-4: GDA-3223797
```

------------------------------------------------------------------------

# CPU e Memória

O projeto não consulta a API GCP para determinar CPU e RAM.

Os valores são mantidos localmente em:

``` yaml
gcp_machine_specs
```

Exemplo:

``` yaml
e2-standard-4:
  cpu: 4
  memory_gb: 16
```

------------------------------------------------------------------------

# Regra de Owner

Fonte única:

``` text
Ambiente + Sistema Operacional
```

Baseado no arquivo:

``` yaml
owner_ids
```

------------------------------------------------------------------------

  Ambiente       SO          Owner
  -------------- ----------- ------------
  Produção       Linux       USR-149372
  Produção       Windows     USR-146496
  Não Produção   Não envia   

------------------------------------------------------------------------

## Importante

``` text
ef_owner NÃO participa desta lógica.
```

------------------------------------------------------------------------

# Interface de Rede

As interfaces são tratadas como objetos independentes do Assets.

Fluxo:

``` text
IP
 ▼
Object Type 230
 ▼
Interface de Rede
 ▼
Servidor
```

Caso a interface não exista:

``` text
Criar automaticamente
Associar ao servidor
```

------------------------------------------------------------------------

# CPU Platform

Suporte para relacionamento com o Object Type:

``` text
232 - CPU
```

Fluxo:

``` text
host.cpuPlatform
      ▼
cpu_platform_map
      ▼
Object ID Assets
```

Exemplo:

``` yaml
cpu_platform_map:
  "Intel Broadwell": "123456"
  "Intel Skylake": "123457"
```

Caso não exista mapeamento:

``` text
O atributo não é enviado
```

------------------------------------------------------------------------

# Variáveis Principais

## AAP

``` yaml
aap_host: https://aap.claro.com.br
aap_inventory_id: 91
```

------------------------------------------------------------------------

## Jira Assets

``` yaml
jira_user
jira_password
workspace
```

------------------------------------------------------------------------

## Proxy

``` yaml
proxy_env:
  http_proxy: http://10.29.177.37:8080
  https_proxy: http://10.29.177.37:8080
```

------------------------------------------------------------------------

# Como Adicionar Novo Machine Type

Adicionar em:

``` yaml
modelo_servidor_map:
```

Exemplo:

``` yaml
novo-machine-type: GDA-999999
```

Adicionar também em:

``` yaml
gcp_machine_specs:
```

Exemplo:

``` yaml
novo-machine-type:
  cpu: 8
  memory_gb: 32
```

Não é necessário alterar:

``` text
gcp_cmdb_filters.py
mapeamento_gcp_cmdb.yml
create.yml
```

------------------------------------------------------------------------

# Script Auxiliar

## discover_attribute_ids.py

Responsável por descobrir IDs de atributos dentro do Jira Assets.

Exemplos:

``` bash
python scripts/discover_attribute_ids.py \
  --object-type 121
```

``` bash
python scripts/discover_attribute_ids.py \
  --object-type 230 \
  --attribute-name Name
```

------------------------------------------------------------------------

------------------------------------------------------------------------

## Manutenção das especificações de máquina

A integração GCP utiliza duas estruturas diferentes no arquivo
`modelo_servidor_map_gcp.yml`:

``` text
modelo_servidor_map
machine_type → objectKey GDA-* do Modelo do Servidor no CMDB

gcp_machine_specs
machine_type → cpu + memory_gb
```

Essas estruturas são consumidas pela transformação dos hosts antes da
criação do payload do Jira Assets.

Ao identificar um novo `machine_type` no inventário AAP, valide:

1.  se o tipo existe em `modelo_servidor_map`;
2.  se existe em `gcp_machine_specs`;
3.  se o Modelo do Servidor correspondente já existe no Object Type 406
    do CMDB.

Diferentemente de AWS e Azure, o projeto fornecido atualmente não contém
um script `coleta_gcp.py`. Portanto, esta documentação não pressupõe
coleta auxiliar direta no GCP.

> O processo normal de sincronização permanece baseado no inventário do
> AAP e não depende de chamadas `gcloud` em tempo de execução.

# Troubleshooting

  Sintoma                        Causa provável
  ------------------------------ -------------------------------------------
  CPU sem valor                  machine_type ausente em gcp_machine_specs
  Memória sem valor              machine_type ausente em gcp_machine_specs
  Host ignorado                  ausência da label ef_cmdb
  Host ignorado                  nó GKE
  Owner não preenchido           ambiente não classificado como Produção
  CPU Platform não preenchido    cpu_platform_map vazio
  Nenhum host encontrado         inventory_id incorreto
  Erro ao acessar AAP            token inválido
  Erro Jira Assets               credenciais inválidas
  Interface de Rede não criada   permissão insuficiente no Assets

------------------------------------------------------------------------

# Roadmap Futuro

Funcionalidades previstas para evolução do projeto:

-   Atualização automática dos ativos existentes.
-   Desativação automática de ativos removidos.
-   Sincronização incremental por evento.
-   Menor tempo de convergência entre GCP e CMDB.
-   Expansão do conjunto de atributos sincronizados.

------------------------------------------------------------------------

# Resumo

O projeto implementa atualmente a integração:

``` text
Google Cloud Platform
        ▼
Inventory GCP do AAP
        ▼
Transformação cloud_data
        ▼
Jira Assets / CMDB
```

Escopo atual:

-   ✅ Descoberta de servidores através do AAP
-   ✅ Transformação para modelo CMDB
-   ✅ Criação automática de ativos
-   ✅ Criação automática de Interfaces de Rede
-   ✅ Associação de CPU Platform
-   ✅ Definição automática de Owner
-   ✅ Exclusão automática de nós GKE
-   ✅ Preservação de dados já existentes no CMDB

Funcionalidades futuras:

-   🔄 Update de ativos existentes
-   🔄 Deactivate de ativos removidos
-   🔄 Sincronização orientada a eventos

================================================================
