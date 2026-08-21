# ☁️ GCP → CMDB | Sincronização de Servidores

> **Objetivo:** manter as VMs GCP refletidas no **Jira Assets (CMDB)** através do **AAP (Ansible Automation Platform)**.

![Status](https://img.shields.io/badge/status-ativo-brightgreen)
![Cloud](https://img.shields.io/badge/cloud-GCP-4285F4)
![Automation](https://img.shields.io/badge/automation-AAP-red)

## 🧭 Em poucas palavras

O projeto faz uma ponte:

**GCP → AAP → tratamento dos dados → CMDB**

Depois da coleta, cada VM pode virar:

| Situação | Ação |
|---|---|
| 🆕 Não existe no CMDB | **CRIAR** |
| 🔄 Existe, foi criada pelo Ansible e o modelo mudou | **ATUALIZAR** |
| 🟢 Já está correta | **SKIP** |
| ♻️ Estava desativada e voltou | **REATIVAR** |
| 🔴 Não existe mais no GCP e foi criada pelo Ansible | **DESATIVAR** |
| 🛡️ Nó GKE | **Protegido** |

O playbook principal é `playbooks/sync_gcp_cmdb.yml`. fileciteturn57file2L325-L336

---

## 🔄 Fluxo

```text
          GCP
           │
           ▼
      Inventário AAP
           │
           ▼
       Filter Python
           │
           ▼
        cloud_data
           │
           ▼
          CMDB
```

O projeto também possui um fluxo opcional de Webhook para eventos do Compute Engine → Pub/Sub → Cloud Function → AAP → CMDB. fileciteturn57file2L5-L18

---

## 🧩 Novo modelo de máquina

O arquivo principal é:

```text
roles/integration_assets_gcp/vars/modelo_servidor_map_gcp.yml
```

Ele faz:

```text
GCP machine_type → GDA do Modelo de Servidor
```

Exemplo:

```yaml
modelo_servidor_map:
  c2-standard-4: GDA-3223797
  e2-medium: GDA-XXXXXXXX
```

O projeto documenta que um novo `machine_type` deve ser incluído nesse mapa e, quando aplicável, também em `gcp_machine_specs`. fileciteturn57file2L2595-L2610

### 🆕 Exemplo completo

Imagine que apareceu:

```text
n4-standard-8
```

### Passo 1 — CMDB

Peça ao time CMDB para criar o modelo no Object Type **Modelo de Servidor (406)**.

Receba:

```text
GDA-3999999
```

### Passo 2 — mapa do modelo

Adicione:

```yaml
modelo_servidor_map:
  n4-standard-8: GDA-3999999
```

### Passo 3 — CPU e memória

Adicione também:

```yaml
gcp_machine_specs:
  n4-standard-8:
    cpu: 8
    memory_gb: 32
```

### Passo 4 — teste

Execute primeiro um teste pequeno.

---

## ⚠️ E se o modelo não existir no CMDB?

Esse é um caso importante.

Se o GCP entregar:

```text
n4-standard-8
```

mas o CMDB não possuir esse modelo, você **não deve criar um GDA manualmente**.

Faça:

```text
1. Identificar machine_type
        ↓
2. Pedir cadastro ao CMDB
        ↓
3. Receber objectKey GDA-XXXXXXX
        ↓
4. Atualizar modelo_servidor_map_gcp.yml
        ↓
5. Atualizar gcp_machine_specs, se necessário
        ↓
6. Testar
```

---

## 🧠 Modelo ≠ CPU/Memória

São mapas diferentes:

| Arquivo | Serve para |
|---|---|
| `modelo_servidor_map_gcp.yml` | machine_type → GDA |
| `gcp_machine_specs` | machine_type → CPU/RAM |
| `mapeamento_gcp_cmdb.yml` | atributo do CMDB → `chave_cloud` |

Exemplo:

```yaml
modelo_servidor_map:
  e2-medium: GDA-322XXXX
```

e:

```yaml
gcp_machine_specs:
  e2-medium:
    cpu: 2
    memory_gb: 4
```

---

## ➕ Como adicionar um campo novo

Imagine que o CMDB ganhou:

```text
Criticidade
```

### 1. Mapeamento

Em:

```text
roles/integration_assets_gcp/vars/mapeamento_gcp_cmdb.yml
```

adicione o atributo:

```yaml
- id: 12345
  name_assets: "Criticidade"
  chave_cloud: "criticidade_cloud"
  tipo: select
```

### 2. Filter

O `cloud_data` precisa produzir:

```python
"criticidade_cloud": valor
```

O filtro percorre os dados e procura cada campo no `object_attribute_map` antes de montar os atributos do CMDB. fileciteturn57file2L2388-L2435

> 💡 **Mapping informa o destino. Filter informa a origem do valor.**

---

## 🧪 Teste seguro

O projeto possui um playbook específico para testar servidores:

```bash
ansible-playbook playbooks/sync_single_gcp.yml \
  -e "test_limit=3" \
  -e "dry_run=true"
```

Também é possível passar uma lista de servidores. fileciteturn57file2L387-L401

---

## 🔔 Webhook GCP

Existe um playbook opcional:

```text
playbooks/setup_webhook.yml
```

Ele configura:

```text
Compute Engine
      ↓
Cloud Logging
      ↓
Log Sink
      ↓
Pub/Sub
      ↓
Cloud Function
      ↓
AAP
      ↓
CMDB
```

Os eventos tratados incluem criação, exclusão, start e stop de VMs. fileciteturn57file2L295-L321

> ⚠️ Esse fluxo exige configuração de APIs, Service Account, token do AAP e permissões no GCP.

---

## 🚨 Problemas comuns

| Sintoma | Verifique |
|---|---|
| `machine_type` novo | Está no `modelo_servidor_map_gcp.yml`? |
| GDA não existe | Solicitar cadastro ao CMDB |
| CPU/RAM vazios | Está no `gcp_machine_specs`? |
| Campo novo não aparece | Filter produz a `chave_cloud`? |
| VM GKE foi processada | Verificar identificação/proteção GKE |
| Webhook não dispara | Pub/Sub, Log Sink, Function e permissões |
| Credencial Jira falhou | `jira_user` / `jira_password` |
| Resultado inesperado | Começar com `dry_run=true` |

---

## 📌 Regra de ouro

Para novo modelo GCP:

```text
machine_type
    ↓
CMDB cria Modelo
    ↓
CMDB entrega GDA-XXXXXXX
    ↓
modelo_servidor_map_gcp.yml
    ↓
gcp_machine_specs
    ↓
Teste
    ↓
Produção
```

**Não invente IDs do CMDB e não coloque IDs diretamente no Python.**
