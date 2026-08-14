# ☁️ GCP — Inventory → CMDB

## 🧭 Em uma frase

Este projeto pega as VMs do **AAP Inventory 91**, transforma os dados GCP e sincroniza os servidores no **Jira Assets**.

```text
GCP
 ↓
Inventory Source
 ↓
AAP Inventory 91
 ↓
transformação
 ↓
Jira Assets
```

---

## 1. 🔑 Acessos

| O quê | Valor/Origem |
|---|---|
| AAP | `https://aap.claro.com.br` |
| Inventory | `91` |
| GCP Credential | injetada pelo AAP |
| variável da credential | `GOOGLE_APPLICATION_CREDENTIALS` |
| Quota Project | `claro-infracloud` |
| Jira | `JIRA_USER` / `JIRA_PASSWORD` |

O código mostra:

```yaml
aap_host: "https://aap.claro.com.br"
aap_inventory_id: "91"
aap_verify_ssl: false

aap_token: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  ...
```

E:

```yaml
jira_user: "{{ lookup('env', 'JIRA_USER') }}"
jira_password: "{{ lookup('env', 'JIRA_PASSWORD') }}"
```

---

## 2. 📥 De onde vêm as VMs?

A origem é:

```text
AAP Inventory 91
```

O código consulta:

```yaml
url: "{{ aap_host }}/api/controller/v2/inventories/{{ aap_inventory_id }}/hosts/?page_size=500"
method: GET
```

Depois busca as variáveis dos hosts:

```yaml
url: "{{ aap_host }}/api/controller/v2/hosts/{{ item.id }}/variable_data/"
```

---

## 3. 🔄 Transformação

Esse é um dos trechos mais importantes:

```yaml
cloud_data_list: >-
  {{ all_host_vars | batch_transform_gcp_hosts(
       modelo_servidor_map | default({}),
       gcp_machine_specs   | default({}),
       owner_ids           | default({}),
       cpu_platform_map    | default({})
     ) }}
```

Leia assim:

```text
host do AAP
    │
    ├── modelo
    ├── CPU/RAM
    ├── owner
    └── CPU platform
    │
    ▼
cloud_data
```

---

## 4. 🖥️ Modelo + CPU + RAM

Arquivo:

```text
vars/modelo_servidor_map_gcp.yml
```

O `machine_type` é a chave.

Exemplo conceitual:

```text
n2-standard-2
      ↓
gcp_machine_specs
      ↓
CPU = 2
RAM = 8 GB
```

O projeto converte a RAM para MB:

```text
8 × 1024
=
8192 MB
```

---

## 5. 👤 Owner

Mesma ideia dos outros projetos:

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

## 6. 🏷️ Labels GCP

O Inventory Source usa:

```yaml
- key: gcp_labels.ef_ambiente | default('SEM_EF_AMBIENTE')
  prefix: "Ambiente"

- key: gcp_labels.ef_cmdb | default('SEM_EF_CMDB')
  prefix: "Sistema"
```

Então:

```text
label ef_ambiente = prd
        ↓
Ambiente-prd
```

---

## 7. 🌐 Qual IP vira `ansible_host`?

Código real:

```yaml
ansible_host: networkInterfaces[0].accessConfigs[0].natIP
  | default(networkInterfaces[0].networkIP, true)
```

Prioridade:

```text
NAT / Public IP
      ↓
Private IP
```

Também são montados:

```yaml
private_ip: networkInterfaces[0].networkIP
public_ip: networkInterfaces[0].accessConfigs[0].natIP
machine_type: machineType | basename
zone: zone | basename
gcp_project: project | basename
gcp_labels: labels | default({})
```

---

## 8. ➕ CREATE / ⏭️ SKIP / ⛔ DEACTIVATE

A ideia:

```text
Host GCP
   ↓
Name já existe no Assets?
   ├── NÃO → CREATE
   └── SIM → SKIP
```

Existe também:

```text
VM desapareceu do GCP
        ↓
DEACTIVATE
```

Mas a configuração padrão é:

```yaml
enable_deactivation: false
```

---

## 9. 🧪 Teste

O próprio playbook documenta três formas:

```bash
# lista
ansible-playbook playbooks/sync_single_gcp.yml \
  -e 'test_servers=["apigee-mig-prod-us-east-4-h29c"]'

# quantidade
ansible-playbook playbooks/sync_single_gcp.yml \
  -e "test_limit=3"

# dry-run
ansible-playbook playbooks/sync_single_gcp.yml \
  -e "test_limit=5" \
  -e "dry_run=true"
```

---

## 10. 🔔 Webhook

O projeto também possui:

```text
playbooks/setup_webhook.yml
```

Fluxo:

```text
Compute Engine
 ↓
Cloud Logging
 ↓
Pub/Sub
 ↓
Cloud Function
 ↓
AAP
 ↓
CMDB
```

Eventos tratados no desenho do projeto incluem:

```text
insert
delete
start
stop
```

---

## 🗺️ Onde mexer?

| Quero mudar... | Arquivo |
|---|---|
| Campos CMDB | `mapeamento_gcp_cmdb.yml` |
| Modelo | `modelo_servidor_map_gcp.yml` |
| CPU/RAM | `gcp_machine_specs` |
| Owner | `owner_ids` |
| CPU Platform | `cpu_platform_map` |
| Coleta | `fetch_all_hosts.yml` |
| Transformação | `main.yml` |
| CREATE | `create.yml` |
| DEACTIVATE | `deactivate.yml` |
| Rede | `manage_network_interface.yml` |
| Teste | `sync_single_gcp.yml` |

---

## 🧠 Resumo

```text
GCP
 ↓
Inventory Source
 ↓
AAP Inventory #91
 ↓
host variables
 ↓
batch_transform_gcp_hosts(...)
 ↓
cloud_data
 ↓
Jira Assets
```
