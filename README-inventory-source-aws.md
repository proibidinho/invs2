# 🔌 Inventory Source AWS

## 🎯 O que este projeto faz?

Ele **não cria servidores no Jira**.

Ele prepara o AAP para descobrir os servidores AWS.

```text
AWS Organization
       ↓
contas ACTIVE
       ↓
Inventory Source AWS
       ↓
AAP Inventory 92
```

---

## 1. 🔑 Configuração

```yaml
controller_host: "https://aap.claro.com.br"
inventory_id: 92
credential_id: 174
execution_environment_id: 25
trigger_sync: true
```

Portanto:

```text
AAP
├── Inventory: 92
├── Credential: 174
└── EE: 25
```

---

## 2. 🔐 Como entra na AWS?

Primeiro o AAP descobre sua identidade.

Depois assume:

```yaml
role_arn: arn:aws:iam::502379209509:role/EC2InventoryRole
role_session_name: aap_inventory_discovery
```

Depois usa as credenciais STS:

```yaml
AWS_ACCESS_KEY_ID: "{{ management_role.sts_creds.access_key }}"
AWS_SECRET_ACCESS_KEY: "{{ management_role.sts_creds.secret_key }}"
AWS_SESSION_TOKEN: "{{ management_role.sts_creds.session_token }}"
```

para executar:

```bash
aws organizations list-accounts --output json
```

---

## 3. 🔎 Quais contas entram?

O código filtra:

```yaml
selectattr('Status', 'equalto', 'ACTIVE')
```

Então:

```text
Conta ACTIVE
   ↓
entra

Conta não ACTIVE
   ↓
ignorada
```

---

## 4. 🔍 Como sabe se precisa criar um source?

O projeto procura os Inventory Sources que já existem.

Depois extrai o Account ID da role:

```text
arn:aws:iam::<ACCOUNT_ID>:role/EC2InventoryRole
```

Resultado:

```text
Conta AWS
   ↓
já tem Inventory Source?
   ├── SIM → não cria
   └── NÃO → cria
```

---

## 5. 🏗️ O que ele cria?

Nome:

```yaml
name: "AWS - {{ item.Name }}"
```

Descrição:

```yaml
description: "Conta {{ item.Id }}"
```

E:

```yaml
source: ec2
inventory: "{{ inventory_id }}"
credential: "{{ credential_id }}"
execution_environment: "{{ execution_environment_id }}"
```

---

## 6. 📦 Configuração do plugin

Trecho real:

```yaml
plugin: amazon.aws.aws_ec2
assume_role_arn: arn:aws:iam::{{ item.Id }}:role/EC2InventoryRole
strict: false

regions:
  - sa-east-1
  - us-east-1

filters:
  instance-state-name: running

hostnames:
  - instance-id
```

### Tradução:

```text
Plugin EC2
 ↓
assume role na conta
 ↓
sa-east-1 / us-east-1
 ↓
somente running
 ↓
hostname = instance-id
```

---

## 7. 🏷️ Grupos

O código cria grupos por:

```yaml
placement.region
platform_details
instance_type
tags.ef_ambiente
tags.ef_cmdb
tags.Name
owner_id
```

Exemplo:

```text
tag ef_ambiente = prd
        ↓
Ambiente-prd
```

---

## 8. 🌐 IP

```yaml
ansible_host: private_ip_address
  | default(public_ip_address)
  | default(private_dns_name)
```

---

## 9. 🔄 Sync automático

Se:

```yaml
trigger_sync: true
```

o projeto chama:

```yaml
url: "{{ controller_host }}/api/controller/v2/inventory_sources/{{ item.json.id }}/update/"
method: POST
```

Então:

```text
criou source
    ↓
trigger_sync = true
    ↓
AAP sincroniza
```

---

## 🧠 Resumo

```text
AWS Organization
 ↓
ACTIVE accounts
 ↓
comparação com AAP
 ↓
source faltando?
 ├── não → nada
 └── sim → cria
             ↓
          sync
```
