# integration_assets_aws

Sincronização de inventário **AWS** (via Ansible Automation Platform)
para **Jira Assets / CMDB**.

O projeto utiliza o inventário AWS sincronizado no **Ansible Automation
Platform (AAP)** como fonte oficial de dados para cadastro de servidores
no CMDB.

Seguindo o mesmo padrão adotado para Azure e GCP, todas as informações
consumidas pelo processo são obtidas diretamente do inventário do AAP,
evitando consultas adicionais à AWS durante o sync.

------------------------------------------------------------------------

# ⚠️ Escopo Atual do Projeto

Embora a arquitetura já possua componentes preparados para operações de
**Create**, **Update** e **Deactivate**, atualmente o projeto está
homologado e suportado apenas para **criação de novos ativos no CMDB**.

Neste momento:

-   ✅ Create: suportado e utilizado em produção.
-   ⚠️ Update: previsto para evolução futura.
-   ⚠️ Deactivate: previsto para evolução futura.

O comportamento atual é:

``` text
Instância existe na AWS e não existe no CMDB
    → CREATE

Instância existe na AWS e já existe no CMDB
    → SKIP

Instância removida da AWS
    → Nenhuma ação
```

A estratégia atual visa garantir um onboarding seguro dos ativos cloud,
preservando dados preenchidos manualmente e evitando atualizações ou
desativações automáticas até que as regras de governança e ownership
sejam formalmente definidas.

------------------------------------------------------------------------

## Arquitetura

``` text
AAP (inventário AWS)
      │
      ▼
Hosts + variables
(API Controller)
      │
      ▼
aws_cmdb_filters.py
      │
      ▼
cloud_data
      │
      ▼
update_asset()
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
├── sync_aws_cmdb.yml
└── sync_single_aws.yml

roles/integration_assets_aws/
├── filter_plugins/
│   └── aws_cmdb_filters.py
├── tasks/
│   ├── main.yml
│   ├── create.yml
│   └── deactivate.yml
└── vars/
    ├── main.yml
    ├── mapeamento_aws_cmdb.yml
    └── modelo_servidor_map_aws.yml

scripts/
└── coleta_aws.py

README.md
```

------------------------------------------------------------------------

## Fluxo Geral

``` text
AWS
  │
  ▼
Inventory Source AWS
(AAP)
  │
  ▼
Buscar Hosts
  │
  ▼
batch_transform_aws_hosts()
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

O projeto não consulta diretamente a API AWS durante a sincronização.

Toda a coleta ocorre a partir do inventário já existente no AAP.

Chamadas utilizadas:

``` http
GET /api/controller/v2/inventories/{inventory_id}/hosts/
```

O inventário AWS já fornece os dados necessários para o processo:

-   instance_id
-   private_dns_name
-   account_id
-   region
-   instance_type
-   tags
-   network interfaces
-   state
-   platform
-   platform_details
-   cpu_options
-   owner_id

Dessa forma não é necessário executar consultas adicionais na AWS
durante o sync.

------------------------------------------------------------------------

## Playbooks

### sync_aws_cmdb.yml

Playbook principal responsável pela sincronização completa entre:

``` text
AAP
  ▼
Jira Assets
```

### Execução

``` bash
JIRA_USER=usuario JIRA_PASSWORD=senha \
ansible-playbook playbooks/sync_aws_cmdb.yml \
-e "sync_mode=full"
```

------------------------------------------------------------------------

### sync_single_aws.yml

Playbook de homologação e testes.

Permite executar o processo somente para hosts específicos.

### Teste por lista

``` bash
ansible-playbook playbooks/sync_single_aws.yml \
-e 'test_servers=["i-abc.sa-east-1.compute.internal"]'
```

### Teste por limite

``` bash
ansible-playbook playbooks/sync_single_aws.yml \
-e "test_limit=5"
```

### Dry Run

``` bash
ansible-playbook playbooks/sync_single_aws.yml \
-e "test_limit=5" \
-e "dry_run=true"
```

Neste modo nenhum objeto é criado.

Somente o conteúdo transformado de `cloud_data` é exibido.

------------------------------------------------------------------------

## Variáveis Principais

Arquivo:

``` text
roles/integration_assets_aws/vars/main.yml
```

  Variável                  Descrição
  ------------------------- ----------------------------
  jira_url                  URL da API Jira Assets
  jira_user                 Usuário Jira
  jira_password             Senha Jira
  aap_host                  Controller AAP
  aap_inventory_id          Inventário AWS
  aap_token                 Token de autenticação
  object_type_id_servidor   Object Type 121
  sync_mode                 full, create ou deactivate
  enable_deactivation       habilita desativação
  proxy_env                 proxy corporativo

------------------------------------------------------------------------

## Funcionamento da Role

A role principal é dividida em cinco fases.

------------------------------------------------------------------------

### Fase 1 --- Coleta dos Hosts

Busca todos os hosts do inventário AWS no AAP.

``` text
AAP Inventory
    ▼
Hosts
    ▼
Variable Data
```

------------------------------------------------------------------------

### Fase 2 --- Transformação

Executa:

``` python
transform_aws_host()
```

ou:

``` python
batch_transform_aws_hosts()
```

Convertendo:

``` text
Host AWS
     ▼
cloud_data
```

------------------------------------------------------------------------

### Fase 3 --- Comparação

Consulta os servidores já existentes no CMDB.

Exemplo de consulta:

``` aql
objectTypeId = 121
AND Datacenter = "AWS"
```

Separando:

``` text
servers_to_create
servers_to_skip
servers_to_deactivate
```

------------------------------------------------------------------------

### Fase 4 --- Sincronização

Atualmente apenas a operação de criação é utilizada.

------------------------------------------------------------------------

#### Create

Instância encontrada no inventário AWS do AAP mas inexistente no CMDB.

``` http
POST /object/create
```

------------------------------------------------------------------------

#### Skip

Instância já cadastrada no CMDB.

Nenhuma alteração é realizada.

O objetivo é preservar informações mantidas manualmente pelas equipes
responsáveis.

------------------------------------------------------------------------

#### Update (futuro)

Já previsto arquiteturalmente.

Ainda não utilizado.

Possíveis atributos:

-   CPU
-   Memória
-   Ambiente
-   Sistema Operacional
-   Owner
-   Modelo de Servidor
-   Interface de Rede

------------------------------------------------------------------------

#### Deactivate (futuro)

Já existem componentes preparados para suportar desativação automática.

Fluxo previsto:

``` text
Instância removida da AWS
         ▼
Existe apenas no CMDB
         ▼
Status = Desativado
```

Apesar disso, esta funcionalidade permanece desabilitada e fora do
escopo atual do projeto.

------------------------------------------------------------------------

### Fase 5 --- Relatório Final

Ao término do processamento:

``` text
Criados
Existentes (Skip)
Desativados
Erros
```

------------------------------------------------------------------------

## Regras de Exclusão (Skip)

O filtro ignora automaticamente:

### Hosts desabilitados

``` yaml
enabled: false
```

### Nós EKS

Detectados através de:

``` text
iam_instance_profile.arn contendo:

:instance-profile/eks-
```

ou tags:

``` text
aws:eks:*
eks:cluster-name
kubernetes.io/cluster/*
```

### Hosts sem sistema CMDB

Quando não existe a tag obrigatória:

``` text
ef_cmdb
```

------------------------------------------------------------------------

## Campos Populados no CMDB

  Atributo (id)                   Origem
  ------------------------------- -------------------------------------------------
  Name (1104)                     instance_id.region.compute.internal
  FQDN (3343)                     private_dns_name
  Sistema Operacional (3358)      platform / platform_details
  Modelo do Servidor (15656)      instance_type → modelo_servidor_map
  CPU Count (3359)                aws_vm_specs\[instance_type\].cpu
  Memória RAM (6840)              aws_vm_specs\[instance_type\].memory_gb \* 1024
  Owner (3381)                    Ambiente + SO + owner_ids
  Ambiente (1922)                 ef_ambiente / environment
  Sistema (9219)                  ef_cmdb
  Interface de Rede (3528)        IP privado e público
  Status (2957)                   state AWS
  Datacenter (3296)               AWS
  Tipo de Infraestrutura (9948)   CLOUD PUBLICA
  Status Discovery (3053)         Running
  SOX (9647)                      false
  IPE (9648)                      false
  Disaster Recovery (10677)       ef_dr / ef_recuperacao_de_desastre
  Grupo Solucionador (7274)       baseado no sistema operacional
  Last User (3357)                Ansible
  Fornecedor (6829)               AWS
  Conta Cloud (10548)             account_id / owner_id

------------------------------------------------------------------------

## Regra de Owner

Fonte única:

``` text
Ambiente + Sistema Operacional + owner_ids
```

Arquivo:

``` text
modelo_servidor_map_aws.yml
```

  Ambiente       SO         Owner
  -------------- ---------- ------------
  Produção       Linux      USR-149372
  Produção       Windows    USR-146496
  Não Produção   Qualquer   Não envia

### Importante

``` text
ef_owner NÃO participa desta lógica.
```

------------------------------------------------------------------------

## Modelo do Servidor

Conversão:

``` text
instance_type
      ▼
modelo_servidor_map
      ▼
GDA-XXXXXXX
```

Exemplo:

``` yaml
t3.medium: GDA-XXXXXXX
m5.large: GDA-XXXXXXX
r5.4xlarge: GDA-XXXXXXX
```

------------------------------------------------------------------------

## CPU e Memória

CPU e memória são obtidos através de:

``` yaml
aws_vm_specs
```

Exemplo:

``` yaml
t3.medium:
  cpu: 2
  memory_gb: 4
```

Não é realizada consulta à API AWS durante o sync.

------------------------------------------------------------------------

## Como Adicionar um Novo Instance Type

Adicionar em:

``` yaml
modelo_servidor_map:
```

Exemplo:

``` yaml
novo.tipo: GDA-XXXXXXX
```

Adicionar também em:

``` yaml
aws_vm_specs:
```

Exemplo:

``` yaml
novo.tipo:
  cpu: 4
  memory_gb: 16
```

Não é necessário alterar:

``` text
aws_cmdb_filters.py
mapeamento_aws_cmdb.yml
create.yml
```

------------------------------------------------------------------------

------------------------------------------------------------------------

## Script auxiliar `scripts/coleta_aws.py`

O script `coleta_aws.py` **não participa da sincronização AAP → CMDB**.
Ele é uma ferramenta auxiliar de manutenção do catálogo de hardware AWS.

Sua função é consultar a AWS CLI para obter, para uma lista controlada
de `instance_type`, a quantidade de vCPUs e a memória de cada modelo. O
resultado é gravado em `aws_instance_specs.yml`.

Fluxo:

``` text
lista modelos_desejados
        │
        ▼
aws ec2 describe-instance-types
        │
        ▼
VCpuInfo.DefaultVCpus
MemoryInfo.SizeInMiB
        │
        ▼
aws_instance_specs.yml
```

### Pré-requisitos

-   Python 3
-   `PyYAML`
-   AWS CLI instalada
-   credenciais AWS válidas
-   permissão para `ec2:DescribeInstanceTypes`
-   acesso à região configurada no script (`sa-east-1` atualmente)

### Execução

A partir da raiz AWS:

``` bash
python scripts/coleta_aws.py
```

O script gera:

``` text
aws_instance_specs.yml
```

com estrutura semelhante a:

``` yaml
aws_instance_specs:
  t3.medium:
    cpu: 2
    memory_gb: 4
```

### Relação com `modelo_servidor_map_aws.yml`

Existem dois conjuntos de informação distintos:

``` text
modelo_servidor_map
instance_type → objectKey GDA-* do Modelo do Servidor no CMDB

aws_vm_specs
instance_type → cpu + memory_gb
```

O `coleta_aws.py` auxilia na obtenção da segunda informação. A saída
deve ser revisada e incorporada ao bloco `aws_vm_specs` utilizado pela
integração. O script **não descobre o objectKey GDA** e **não altera
automaticamente** `modelo_servidor_map_aws.yml`.

Sempre que um novo `instance_type` entrar no inventário, valide:

1.  se existe em `modelo_servidor_map`;
2.  se existe em `aws_vm_specs`;
3.  se o modelo correspondente já existe no Object Type 406 do CMDB.

> Importante: o sync normal continua usando exclusivamente os dados do
> inventário AAP. A consulta direta à AWS ocorre somente quando este
> script auxiliar é executado manualmente para manutenção do catálogo.

## Troubleshooting

  -----------------------------------------------------------------------
  Sintoma                     Causa provável
  --------------------------- -------------------------------------------
  CPU não aparece             instance_type ausente de aws_vm_specs

  Memória não aparece         instance_type ausente de aws_vm_specs

  Owner não preenchido        tag ef_ambiente não classificada como
                              Produção

  Host ignorado               ausência da tag ef_cmdb

  Host ignorado               nó EKS

  Servidor não criado         já existe no CMDB (skip)

  Nenhum host encontrado      inventário AAP incorreto

  Erro de autenticação        token AAP inválido

  Erro Jira Assets            credenciais inválidas
  -----------------------------------------------------------------------

Ative logs detalhados com:

``` bash
-vvv
```

------------------------------------------------------------------------

## Roadmap Futuro

Funcionalidades previstas:

-   Atualização automática de atributos existentes.
-   Desativação automática de ativos removidos.
-   Sincronização incremental.
-   Expansão de atributos sincronizados.
-   Integração baseada em eventos cloud.

------------------------------------------------------------------------

## Resumo

O projeto implementa atualmente a integração:

``` text
AWS
  ▼
Inventory AWS do AAP
  ▼
Transformação cloud_data
  ▼
Jira Assets / CMDB
```

### Escopo atual

-   ✅ Descoberta de instâncias através do AAP
-   ✅ Transformação para modelo CMDB
-   ✅ Criação automática de novos ativos
-   ✅ Mapeamento de CPU e Memória
-   ✅ Definição automática de Owner
-   ✅ Exclusão automática de nós EKS
-   ✅ Preservação de dados existentes no CMDB

### Funcionalidades futuras

-   🔄 Update automático de ativos existentes
-   🔄 Deactivate automático de ativos removidos
-   🔄 Sincronização incremental baseada em eventos

================================================================
