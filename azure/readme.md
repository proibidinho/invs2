# integration_assets_azure

Sincronização de inventário **Azure** (via Ansible Automation Platform) para **Jira Assets / CMDB**.

O projeto utiliza o inventário Azure sincronizado no **Ansible Automation Platform (AAP)** como fonte oficial de dados para cadastro de servidores no CMDB.

Seguindo o mesmo padrão adotado para AWS e GCP, todas as informações consumidas pelo processo são obtidas diretamente do inventário do AAP, evitando consultas adicionais à Azure durante o sync.

---

# ⚠️ Escopo Atual do Projeto

Embora a arquitetura já possua componentes preparados para operações de **Create**, **Update** e **Deactivate**, atualmente o projeto está homologado e suportado apenas para **criação de novos ativos no CMDB**.

Neste momento:

- ✅ Create: suportado e utilizado em produção.
- ⚠️ Update: previsto para evolução futura.
- ⚠️ Deactivate: previsto para evolução futura.

O comportamento atual é:

```text
VM existe na Azure e não existe no CMDB
    → CREATE

VM existe na Azure e já existe no CMDB
    → SKIP

VM removida da Azure
    → Nenhuma ação
```

A estratégia atual visa garantir um onboarding seguro dos ativos cloud, preservando dados preenchidos manualmente e evitando atualizações ou desativações automáticas até que as regras de governança e ownership sejam formalmente definidas.

---

## Arquitetura

```text
AAP (inventário Azure)
      │
      ▼
Hosts + Variable Data
(API Controller)
      │
      ▼
azure_cmdb_filters.py
      │
      ▼
cloud_data
      │
      ▼
update_asset_azure()
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

---

## Estrutura de arquivos

```text
playbooks/
├── sync_azure_cmdb.yml
└── sync_single_azure.yml

roles/integration_assets_azure/
├── filter_plugins/
│   └── azure_cmdb_filters.py
├── tasks/
│   ├── main.yml
│   ├── create.yml
│   ├── deactivate.yml
│   └── manage_network_interface.yml
└── vars/
    ├── main.yml
    ├── mapeamento_azure_cmdb.yml
    └── modelo_servidor_map_azure.yml

README.md
```

---

## Fluxo Geral

```text
Azure
  │
  ▼
Inventory Source Azure
(AAP)
  │
  ▼
Buscar Hosts
  │
  ▼
Buscar Variable Data
  │
  ▼
batch_transform_azure_hosts()
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

---

## Fonte dos Dados

O projeto não consulta diretamente a API Azure durante a sincronização.

Toda a coleta ocorre a partir do inventário já existente no AAP.

Chamadas utilizadas:

```http
GET /api/controller/v2/inventories/{inventory_id}/hosts/
```

```http
GET /api/controller/v2/hosts/{host_id}/variable_data/
```

O inventário Azure já fornece os dados necessários para o processo:

- azure_vm_name
- virtual_machine_size
- resource_group
- powerstate
- network interfaces
- public IPs
- private IPs
- image information
- operating system type
- tags
- vmid

Dessa forma não é necessário executar consultas adicionais na Azure durante o sync.

---

## Playbooks

### sync_azure_cmdb.yml

Playbook principal responsável pela sincronização completa entre:

```text
AAP
  ▼
Jira Assets
```

### Execução

```bash
JIRA_USER=usuario JIRA_PASSWORD=senha \
ansible-playbook playbooks/sync_azure_cmdb.yml \
-e "sync_mode=full"
```

---

### sync_single_azure.yml

Playbook de homologação e testes.

Permite executar o processo somente para VMs específicas.

### Teste por lista

```bash
ansible-playbook playbooks/sync_single_azure.yml \
-e 'test_servers=["azlxprd001","azwinprd002"]'
```

### Teste por limite

```bash
ansible-playbook playbooks/sync_single_azure.yml \
-e "test_limit=5"
```

### Dry Run

```bash
ansible-playbook playbooks/sync_single_azure.yml \
-e "test_limit=5" \
-e "dry_run=true"
```

Neste modo nenhum objeto é criado.

Somente o conteúdo transformado de `cloud_data` é exibido.

---

## Variáveis Principais

Arquivo:

```text
roles/integration_assets_azure/vars/main.yml
```

| Variável | Descrição |
|-----------|------------|
| jira_url | URL da API Jira Assets |
| jira_user | Usuário Jira |
| jira_password | Senha Jira |
| aap_host | Controller AAP |
| aap_inventory_id | Inventário Azure |
| aap_token | Token de autenticação |
| object_type_id_servidor | Object Type 121 |
| object_type_id_interface_rede | Object Type 230 |
| sync_mode | full, create ou deactivate |
| enable_deactivation | habilita desativação |
| proxy_env | proxy corporativo |

---

## Funcionamento da Role

A role principal é dividida em cinco fases.

---

### Fase 1 — Coleta dos Hosts

Busca todos os hosts do inventário Azure no AAP.

```text
AAP Inventory
    ▼
Hosts
    ▼
Variable Data
```

---

### Fase 2 — Transformação

Executa:

```python
transform_azure_host()
```

ou:

```python
batch_transform_azure_hosts()
```

Convertendo:

```text
Host Azure
      ▼
cloud_data
```

---

### Fase 3 — Comparação

Consulta os servidores já existentes no CMDB.

Exemplo de consulta:

```aql
objectTypeId = 121
AND Datacenter = "Azure"
```

Separando:

```text
servers_to_create
servers_to_skip
servers_to_deactivate
```

---

### Fase 4 — Sincronização

Atualmente apenas a operação de criação é utilizada.

---

#### Create

VM encontrada no inventário Azure do AAP mas inexistente no CMDB.

```http
POST /object/create
```

---

#### Skip

VM já cadastrada no CMDB.

Nenhuma alteração é realizada.

O objetivo é preservar informações mantidas manualmente pelas equipes responsáveis.

---

#### Update (futuro)

Já previsto arquiteturalmente.

Ainda não utilizado.

Possíveis atributos:

- CPU
- Memória
- Ambiente
- Sistema Operacional
- Owner
- Modelo de Servidor
- Interface de Rede
- Resource Group

---

#### Deactivate (futuro)

Já existem componentes preparados para suportar desativação automática.

Fluxo previsto:

```text
VM removida da Azure
       ▼
Existe apenas no CMDB
       ▼
Status = Desativado
```

Apesar disso, esta funcionalidade permanece desabilitada e fora do escopo atual do projeto.

---

### Fase 5 — Relatório Final

Ao término do processamento:

```text
Criados
Existentes (Skip)
Desativados
Erros
```

---

## Regras de Exclusão (Skip)

O filtro ignora automaticamente:

### Hosts desabilitados

```yaml
enabled: false
```

### Nós AKS

Detectados através de:

```text
resource_group iniciando com:

MC_
```

ou tags:

```text
aks-managed-*
orchestrator=kubernetes
```

### Hosts sem sistema CMDB

Quando não existe a tag obrigatória:

```text
ef_cmdb
```

---

## Campos Populados no CMDB

| Atributo (id) | Origem |
|---------------|---------|
| Name (1104) | azure_vm_name / host.name |
| FQDN (3343) | public_dns_hostnames[0] ou fallback name-vmid |
| Sistema Operacional (3358) | os_disk.operating_system_type / image.offer |
| Modelo do Servidor (15656) | virtual_machine_size → modelo_servidor_map |
| CPU Count (3359) | azure_vm_specs[vm_size].cpu |
| Memória RAM (6840) | azure_vm_specs[vm_size].memory_gb * 1024 |
| Owner (3381) | Ambiente + SO + owner_ids |
| Ambiente (1922) | ef_ambiente |
| Sistema (9219) | ef_cmdb |
| Interface de Rede (3528) | IPs privados e públicos |
| Status (2957) | powerstate Azure |
| Datacenter (3296) | Azure |
| Tipo de Infraestrutura (9948) | CLOUD PUBLICA |
| Status Discovery (3053) | Running |
| SOX (9647) | false |
| IPE (9648) | false |
| Disaster Recovery (10677) | ef_dr / ef_recuperacao_de_desastre |
| Grupo Solucionador (7274) | baseado no sistema operacional |
| Last User (3357) | Ansible |
| Fornecedor (6829) | Azure |
| Conta Cloud (10548) | resource_group |

---

## Regra de Owner

Fonte única:

```text
Ambiente + Sistema Operacional + owner_ids
```

Arquivo:

```text
modelo_servidor_map_azure.yml
```

| Ambiente | SO | Owner |
|-----------|------|--------|
| Produção | Linux | USR-149372 |
| Produção | Windows | USR-146496 |
| Não Produção | Qualquer | Não envia |

### Importante

```text
ef_owner NÃO participa desta lógica.
```

---

## Interface de Rede

As interfaces são tratadas como objetos independentes do Assets.

Fluxo:

```text
IP
 ▼
Object Type 230
 ▼
Interface de Rede
 ▼
Servidor
```

Caso a interface não exista:

```text
Criar automaticamente
Associar ao servidor
```

---

## Modelo do Servidor

Conversão:

```text
virtual_machine_size
          ▼
modelo_servidor_map
          ▼
GDA-XXXXXXX
```

Exemplo:

```yaml
Standard_D2s_v5: GDA-XXXXXXX
Standard_D4s_v5: GDA-XXXXXXX
Standard_E8s_v5: GDA-XXXXXXX
```

---

## CPU e Memória

CPU e memória são obtidos através de:

```yaml
azure_vm_specs
```

Exemplo:

```yaml
Standard_D4s_v5:
  cpu: 4
  memory_gb: 16
```

Não é realizada consulta à API Azure durante o sync.

---

## Como Adicionar um Novo Virtual Machine Size

Adicionar em:

```yaml
modelo_servidor_map:
```

Exemplo:

```yaml
Standard_XX_v9: GDA-XXXXXXX
```

Adicionar também em:

```yaml
azure_vm_specs:
```

Exemplo:

```yaml
Standard_XX_v9:
  cpu: 8
  memory_gb: 32
```

Não é necessário alterar:

```text
azure_cmdb_filters.py
mapeamento_azure_cmdb.yml
create.yml
```

---

## Troubleshooting

| Sintoma | Causa provável |
|----------|----------------|
| CPU não aparece | virtual_machine_size ausente de azure_vm_specs |
| Memória não aparece | virtual_machine_size ausente de azure_vm_specs |
| Owner não preenchido | tag ef_ambiente não classificada como Produção |
| Host ignorado | ausência da tag ef_cmdb |
| Host ignorado | nó AKS |
| Servidor não criado | já existe no CMDB (skip) |
| Nenhum host encontrado | inventário AAP incorreto |
| Timeout na busca AAP | conectividade/proxy/API Controller |
| Erro de autenticação | token AAP inválido |
| Erro Jira Assets | credenciais inválidas |

Ative logs detalhados com:

```bash
-vvv
```

---

## Roadmap Futuro

Funcionalidades previstas:

- Atualização automática de atributos existentes.
- Desativação automática de ativos removidos.
- Sincronização incremental.
- Expansão de atributos sincronizados.
- Integração baseada em eventos cloud.

---

## Resumo

O projeto implementa atualmente a integração:

```text
Azure
  ▼
Inventory Azure do AAP
  ▼
Transformação cloud_data
  ▼
Jira Assets / CMDB
```

### Escopo atual

- ✅ Descoberta de VMs através do AAP
- ✅ Transformação para modelo CMDB
- ✅ Criação automática de novos ativos
- ✅ Criação automática de Interfaces de Rede
- ✅ Mapeamento de CPU e Memória
- ✅ Definição automática de Owner
- ✅ Exclusão automática de nós AKS
- ✅ Preservação de dados existentes no CMDB

### Funcionalidades futuras

- 🔄 Update automático de ativos existentes
- 🔄 Deactivate automático de ativos removidos
- 🔄 Sincronização incremental baseada em eventos