# ☁️ Azure — Inventory → CMDB

## 🧭 Em uma frase

Este projeto pega as VMs do **AAP Inventory 93**, transforma os dados Azure e sincroniza os servidores no **Jira Assets**.

```text
Azure
 ↓
Inventory Source Azure
 ↓
AAP Inventory 93
 ↓
transformação
 ↓
Jira Assets
```

> 💡 Comece por `playbooks/sync_azure_cmdb.yml` e depois vá para `roles/integration_assets_azure/tasks/main.yml`.

---

## 1. 🔑 Acessos

| O quê | Valor/Origem |
|---|---|
| AAP | `https://aap.claro.com.br` |
| Inventory | `93` |
| Credential global Azure | `226` |
| Nome da Credential | `Credential Azure Claro-Management` |
| Credential Type | `10` |
| Execution Environment | `31` |
| AAP token | Vault |
| Jira | `JIRA_USER` / `JIRA_PASSWORD` |

O código mostra:

```yaml
controller_host: "https://aap.claro.com.br"

inventory_id: 93
execution_environment_id: 31

credential_type_id: 10
template_credential_id: 226 #Credential Azure Claro-Management
```

---

## 2. 📥 De onde vêm as VMs?

O projeto consulta o Inventory do AAP:

```text
AAP Inventory 93
      ↓
Hosts Azure
```

Depois busca as variáveis de cada host.

A ideia é simples:

```text
AAP
 ↓
nome da VM
 ↓
IP
 ↓
tags
 ↓
resource group
 ↓
location
 ↓
transformação
```

---

## 3. 🪪 Como o Azure chega ao AAP?

Aqui está uma diferença importante em relação ao AWS.

No Azure existe:

```text
Credential Global #226
        ↓
descobre subscriptions
        ↓
Credential AAP por subscription
        ↓
Inventory Source por subscription
```

O código realmente faz:

```yaml
azure.azcollection.azure_rm_subscription_info:
```

Depois filtra:

```yaml
selectattr('state', 'equalto', 'Enabled')
```

Portanto:

> somente subscriptions Azure **Enabled** entram no processo.

---

## 4. 🔐 Credential por subscription

O código cria a credential assim:

```yaml
inputs:
  subscription: "{{ item.id }}"
  client: "{{ template_credential.json.inputs.client }}"
  secret: "{{ azure_client_secret }}"
  tenant: "{{ template_credential.json.inputs.tenant }}"
  cloud_environment: ""
```

Leia isso como:

```text
Subscription atual
       +
Client da Credential Global
       +
Secret do runtime
       +
Tenant da Credential Global
       ↓
Credential Azure no AAP
```

🔐 O secret real não deve aparecer no README.

---

## 5. 📦 Inventory Source Azure

Cada subscription pode ter seu próprio source.

O código cria:

```yaml
name: "Fonte Azure - {{ item.name | lower }}"
description: "{{ item.id }}"

source: azure_rm
inventory: "{{ inventory_id }}"
credential: "{{ credential_map[item.id] }}"
execution_environment: "{{ execution_environment_id }}"
```

Então:

```text
Subscription A
   ↓
Credential A
   ↓
Fonte Azure - A

Subscription B
   ↓
Credential B
   ↓
Fonte Azure - B
```

---

## 6. 🔎 O que o Inventory Source busca?

O plugin é:

```yaml
plugin: azure.azcollection.azure_rm
auth_source: auto

include_vm_resource_groups:
  - '*'
```

Ou seja:

```text
Azure Subscription
      ↓
todos os Resource Groups
      ↓
VMs
      ↓
AAP Inventory
```

---

## 7. 🏷️ Tags viram grupos

O código diz:

```yaml
- key: tags.ef_ambiente | default('SEM_EF_AMBIENTE')
  prefix: Ambiente
  separator: "-"

- key: tags.ef_cmdb | default('SEM_EF_CMDB')
  prefix: Sistema
  separator: "-"
```

Então:

```text
ef_ambiente = prd
      ↓
Ambiente-prd
```

e:

```text
ef_cmdb = GDA-123
      ↓
Sistema-GDA-123
```

Também existe:

```yaml
- key: location | default('desconhecida')
  prefix: Local
```

---

## 8. 🐧 Linux x 🪟 Windows

O próprio Inventory Source cria grupos:

```yaml
conditional_groups:
  VMs_Linux: "'linux' in (image.offer | default('') | lower)"
  VMs_Windows: "'windows' in (image.offer | default('') | lower)"
```

Então:

```text
image.offer contém "linux"
        ↓
VMs_Linux
```

ou:

```text
image.offer contém "windows"
        ↓
VMs_Windows
```

---

## 9. 🌐 Qual IP vira `ansible_host`?

O código:

```yaml
ansible_host: private_ipv4_addresses[0]
  | default(public_ipv4_addresses[0] | default(''))
```

Prioridade:

```text
Private IP
   ↓
Public IP
```

Também são criados:

```yaml
azure_vm_name: name
azure_resource_group: resource_group
azure_location: location
azure_private_ip: private_ipv4_addresses[0]
azure_public_ip: public_ipv4_addresses[0]
```

---

## 10. 🖥️ Modelo + CPU + RAM

Quando o projeto encontra:

```text
vm_size
```

procure:

```text
vars/modelo_servidor_map_azure.yml
```

A ideia é:

```text
Standard_D4s_v3
       ↓
modelo_servidor_map
       ↓
Modelo do Servidor

Standard_D4s_v3
       ↓
azure_vm_specs
       ↓
CPU + RAM
```

---

## 11. 👤 Owner

A lógica é:

```text
Ambiente + SO
      ↓
owner_ids
      ↓
USR-...
```

Atualmente:

```text
Produção + Linux    → USR-149372
Produção + Windows  → USR-146496
Não Produção        → USR-129988
```

---

## 12. ➕ CREATE / ⏭️ SKIP / ⛔ DEACTIVATE

Pense assim:

```text
VM do AAP
   ↓
Name já existe?
   ├── NÃO → CREATE
   └── SIM → SKIP
```

A desativação existe separadamente.

Configuração padrão:

```yaml
sync_mode: "full"
enable_deactivation: false
```

---

## 13. 🧪 Teste

```bash
ansible-playbook playbooks/sync_single_azure.yml \
  -e "test_limit=5" \
  -e "dry_run=true"
```

Ou:

```bash
ansible-playbook playbooks/sync_single_azure.yml \
  -e 'test_servers=["vm01","vm02"]'
```

---

## 🗺️ Onde mexer?

| Quero mudar... | Arquivo |
|---|---|
| Campos CMDB | `mapeamento_azure_cmdb.yml` |
| Modelo | `modelo_servidor_map_azure.yml` |
| CPU/RAM | `azure_vm_specs` |
| Owner | `owner_ids` |
| Coleta | `fetch_all_hosts.yml` |
| Transformação | `main.yml` |
| CREATE | `create.yml` |
| DEACTIVATE | `deactivate.yml` |
| Rede | `manage_network_interface.yml` |
| Teste | `sync_single_azure.yml` |

---

## 🧠 Resumo

```text
Azure
 ↓
Subscriptions Enabled
 ↓
Inventory Source por subscription
 ↓
AAP Inventory #93
 ↓
VM + tags + IP + vm_size
 ↓
mapeamentos
 ↓
cloud_data
 ↓
Jira Assets
```
