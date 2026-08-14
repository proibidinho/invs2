# 🔌 Inventory Source Azure

## 🎯 O que este projeto faz?

Ele cria e mantém:

```text
Credential Azure
       +
Inventory Source Azure
```

para cada subscription habilitada.

```text
Azure
 ↓
Subscriptions Enabled
 ↓
Credential AAP por subscription
 ↓
Inventory Source por subscription
 ↓
AAP Inventory 93
```

---

## 1. 🔑 Configuração

```yaml
controller_host: "https://aap.claro.com.br"

inventory_id: 93
execution_environment_id: 31
credential_type_id: 10
template_credential_id: 226
```

A Credential 226 está identificada no código como:

```yaml
template_credential_id: 226 #Credential Azure Claro-Management
```

---

## 2. 📥 Descobrir subscriptions

O código:

```yaml
azure.azcollection.azure_rm_subscription_info:
```

Depois:

```yaml
selectattr('state', 'equalto', 'Enabled')
```

Ou seja:

```text
Azure
 ↓
subscriptions
 ↓
Enabled only
```

---

## 3. 🔐 Criar Credential

O trecho mais importante é:

```yaml
inputs:
  subscription: "{{ item.id }}"
  client: "{{ template_credential.json.inputs.client }}"
  secret: "{{ azure_client_secret }}"
  tenant: "{{ template_credential.json.inputs.tenant }}"
  cloud_environment: ""
```

Isso explica exatamente a arquitetura:

```text
Credential Global #226
      │
      ├── client
      └── tenant
            +
      secret do runtime
            +
      subscription atual
            ↓
Credential Azure
```

---

## 4. 🔍 Não cria duplicado

Antes de criar:

```yaml
when:
  - item.id not in credential_map
```

Então:

```text
subscription já possui credential?
        │
   ┌────┴────┐
   SIM       NÃO
    ↓         ↓
 reutiliza   cria
```

---

## 5. 📦 Criar Inventory Source

Trecho real:

```yaml
name: "Fonte Azure - {{ item.name | lower }}"
description: "{{ item.id }}"

source: azure_rm
inventory: "{{ inventory_id }}"
credential: "{{ credential_map[item.id] }}"
execution_environment: "{{ execution_environment_id }}"
```

Assim:

```text
Subscription
   ↓
Credential correspondente
   ↓
Fonte Azure - subscription
   ↓
Inventory #93
```

---

## 6. ⚙️ Plugin Azure

```yaml
plugin: azure.azcollection.azure_rm
auth_source: auto

include_vm_resource_groups:
  - '*'
```

Significa:

```text
Subscription
 ↓
todos os Resource Groups
 ↓
VMs
```

---

## 7. 🏷️ Grupos

```yaml
- key: tags.ef_ambiente | default('SEM_EF_AMBIENTE')
  prefix: Ambiente

- key: tags.ef_cmdb | default('SEM_EF_CMDB')
  prefix: Sistema

- key: location | default('desconhecida')
  prefix: Local
```

E Linux/Windows:

```yaml
conditional_groups:
  VMs_Linux: "'linux' in (image.offer | default('') | lower)"
  VMs_Windows: "'windows' in (image.offer | default('') | lower)"
```

---

## 8. 🌐 IP

```yaml
ansible_host: private_ipv4_addresses[0]
  | default(public_ipv4_addresses[0] | default(''))
```

---

## 9. 🔄 Sync

Depois de criar o source:

```yaml
url: "{{ controller_host }}/api/controller/v2/inventory_sources/{{ item.json.id }}/update/"
method: POST
```

Portanto:

```text
criou
 ↓
sync
```

---

## 🧠 Resumo

```text
Credential #226
 ↓
subscriptions Enabled
 ↓
credentials por subscription
 ↓
sources por subscription
 ↓
AAP Inventory #93
```
