# ☁️ AWS — Inventory → CMDB

## 🧭 Em uma frase

Este projeto pega os servidores que já foram descobertos no **AAP Inventory 92**, transforma os dados AWS e envia os objetos para o **Jira Assets**.

```text
AWS
 ↓
Inventory Source
 ↓
AAP Inventory 92
 ↓
transformação
 ↓
Jira Assets
```

> 💡 **Para entender o projeto, comece por:** `playbooks/sync_aws_cmdb.yml` → `roles/integration_assets_aws/tasks/main.yml`.

---

## 1. 🔑 Onde está cada acesso?

| O quê | Onde |
|---|---|
| AAP | `https://aap.claro.com.br` |
| Inventory | `92` |
| AWS Credential do Inventory Source | `174` |
| Execution Environment | `25` |
| AAP token | Vault (`aap_token`) |
| Jira usuário | `JIRA_USER` |
| Jira senha | `JIRA_PASSWORD` |

No código, a configuração do projeto segue este padrão:

```yaml
aap_host: "https://aap.claro.com.br"
aap_inventory_id: "92"
aap_verify_ssl: false

aap_token: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  ...
```

E o Jira é obtido do ambiente:

```yaml
jira_user: "{{ lookup('env', 'JIRA_USER') }}"
jira_password: "{{ lookup('env', 'JIRA_PASSWORD') }}"
```

🔐 **Não coloque o valor real dessas credenciais no README/Git.**

---

## 2. 📥 De onde vêm os servidores?

O projeto **não consulta diretamente a AWS para montar o CMDB**.

Ele consulta o Inventory do AAP:

```text
AAP
└── Inventory 92
    └── Hosts AWS
```

A coleta é feita pela API:

```yaml
url: "{{ aap_host }}/api/controller/v2/inventories/{{ aap_inventory_id }}/hosts/?page_size=500"
method: GET
headers:
  Authorization: "Bearer {{ aap_token }}"
```

### O que isso significa?

Se uma VM não estiver no **Inventory 92**, ela não chega nessa etapa do projeto.

---

## 3. 🔄 O caminho dos dados

```text
┌─────────────┐
│ AAP #92     │
└──────┬──────┘
       │ hosts
       ▼
┌─────────────────────┐
│ coleta/paginação    │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│ transformação AWS   │
│ host → cloud_data   │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│ modelo + specs      │
│ owner + tags        │
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│ Jira Assets         │
└─────────────────────┘
```

---

## 4. 🧩 Onde os dados são transformados?

Os mapas ficam em:

```text
roles/integration_assets_aws/vars/
├── main.yml
├── mapeamento_aws_cmdb.yml
└── modelo_servidor_map_aws.yml
```

A ideia é:

```text
AWS host
  ↓
instance_type / tags / IP / etc.
  ↓
modelo_servidor_map_aws.yml
  ↓
cloud_data
  ↓
Jira
```

### Exemplo de código

O projeto usa o `instance_type` para descobrir informações adicionais:

```yaml
instance_type: instance_type
platform: platform_details | default('Linux/UNIX')
private_ip: private_ip_address | default('')
public_ip: public_ip_address | default('N/A')
region: placement.region
account_id: owner_id | string
```

---

## 5. 🖥️ CPU, RAM e Modelo

Existe uma separação importante:

```text
modelo_servidor_map_aws.yml
        │
        ├── modelo do servidor
        ├── aws_vm_specs
        └── owner_ids
```

Então, se aparecer um novo tipo:

```text
m5.4xlarge
```

não saia alterando a lógica principal.

Primeiro procure:

```text
modelo_servidor_map_aws.yml
```

---

## 6. 👤 Owner

A regra de Owner está no mapa do projeto.

A forma simples de pensar é:

```text
Ambiente
   +
Sistema Operacional
   ↓
owner_ids
   ↓
USR-...
```

Os IDs atualmente documentados no projeto são:

```text
Produção + Linux    → USR-149372
Produção + Windows  → USR-146496
Não Produção        → USR-129988
```

---

## 7. 🏷️ Tags AWS são importantes

O Inventory Source cria grupos a partir de tags.

Exemplo real:

```yaml
- key: tags.ef_ambiente | default('SEM_AMBIENTE') | lower
  prefix: Ambiente
  separator: "-"

- key: tags.ef_cmdb | default('SEM_SISTEMA')
  prefix: Sistema
  separator: "-"
```

Portanto:

```text
tag ef_ambiente = prd
        ↓
Ambiente-prd
```

E:

```text
tag ef_cmdb = GDA-123
        ↓
Sistema-GDA-123
```

---

## 8. 🌐 Qual IP vira `ansible_host`?

Está explícito no Inventory Source:

```yaml
ansible_host: private_ip_address
  | default(public_ip_address)
  | default(private_dns_name)
```

Ou seja:

```text
Private IP
   ↓ se não existir
Public IP
   ↓ se não existir
Private DNS
```

---

## 9. ➕ CREATE / ⏭️ SKIP / ⛔ DEACTIVATE

A lógica do projeto pode ser entendida assim:

```text
Host AAP
   ↓
já existe no Assets?
   ├── NÃO → CREATE
   └── SIM → SKIP
```

Para objetos que desapareceram da origem existe também a lógica de `DEACTIVATE`.

O default atual é:

```yaml
enable_deactivation: false
```

Portanto, **não presuma que desativação está ligada só porque existe `deactivate.yml`**.

---

## 10. 🧪 Como testar sem pegar tudo?

Existe um playbook específico:

```text
playbooks/sync_single_aws.yml
```

O padrão do projeto permite:

```bash
ansible-playbook playbooks/sync_single_aws.yml \
  -e "test_limit=5" \
  -e "dry_run=true"
```

Ou uma lista:

```bash
ansible-playbook playbooks/sync_single_aws.yml \
  -e 'test_servers=["srv01","srv02"]'
```

---

## 🗺️ Mapa rápido para manutenção

| Quero mudar... | Olhe primeiro... |
|---|---|
| Campo enviado ao CMDB | `mapeamento_aws_cmdb.yml` |
| Modelo | `modelo_servidor_map_aws.yml` |
| CPU/RAM | `aws_vm_specs` |
| Owner | `owner_ids` |
| Coleta do AAP | `fetch_all_hosts.yml` |
| Transformação | `main.yml` / filtro de transformação |
| CREATE | `create.yml` |
| DEACTIVATE | `deactivate.yml` |
| Rede | `manage_network_interface.yml` |
| Teste | `sync_single_aws.yml` |

---

## 🧠 Resumo para o próximo analista

```text
NÃO começa pela AWS.

Começa aqui:
        ↓
AAP Inventory #92
        ↓
transformação
        ↓
vars/modelo_servidor_map_aws.yml
        ↓
cloud_data
        ↓
Jira Assets
```
