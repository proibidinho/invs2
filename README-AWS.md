# ☁️ AWS → CMDB | Sincronização de Servidores

> **Objetivo:** manter os servidores EC2 do AWS refletidos no **Jira Assets (CMDB)** através do **AAP (Ansible Automation Platform)**.

![Status](https://img.shields.io/badge/status-ativo-brightgreen)
![Cloud](https://img.shields.io/badge/cloud-AWS-orange)
![Automation](https://img.shields.io/badge/automation-AAP-red)

## 🧭 Em poucas palavras

Pense no projeto como uma **ponte**:

**AWS → AAP → tratamento dos dados → CMDB**

O AAP consulta os servidores AWS, transforma os dados para o formato do CMDB e decide o que fazer:

| Situação | Ação |
|---|---|
| 🆕 Servidor não existe no CMDB | **CRIAR** |
| 🔄 Servidor existe, foi criado pelo Ansible e o modelo mudou | **ATUALIZAR** |
| 🟢 Servidor existe e não precisa mudança | **SKIP** |
| ♻️ Servidor estava desativado e voltou | **REATIVAR** |
| 🔴 Servidor não existe mais na AWS e foi criado pelo Ansible | **DESATIVAR** |
| 🛡️ Nó EKS | **Protegido** |

O playbook principal é `playbooks/sync_aws_cmdb.yml`; também existe um playbook para testar servidores selecionados. fileciteturn57file1L5-L9

---

## 🔄 Como funciona

```text
        AWS
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
    ┌────┴────┐
    │         │
  CREATE   UPDATE/SKIP
```

O projeto identifica nós EKS pelas tags próprias do cluster, evitando tratar máquinas de Kubernetes como servidores comuns. fileciteturn57file1L389-L400

---

## 🧩 Onde mexer quando surgir um novo modelo

O arquivo mais importante é:

```text
roles/integration_assets_aws/vars/modelo_servidor_map_aws.yml
```

Ele faz a tradução:

```yaml
modelo_servidor_map:
  m6i.xlarge: GDA-3223765
  m7i.xlarge: GDA-3223782
```

Ou seja:

> **instance_type da AWS → objeto "Modelo do Servidor" no CMDB**

O próprio projeto orienta que, para um novo `instance_type`, basta adicionar a entrada nesse arquivo; não é necessário alterar o filtro Python nem o `mapeamento_aws_cmdb.yml`. fileciteturn57file1L2127-L2143

### 🆕 Exemplo

A AWS começa a entregar:

```text
m8i.2xlarge
```

O time de CMDB precisa primeiro criar esse modelo no Object Type **Modelo de Servidor (406)**.

Depois, você recebe o `objectKey`, por exemplo:

```text
GDA-3999999
```

E adiciona:

```yaml
modelo_servidor_map:
  m8i.2xlarge: GDA-3999999
```

### ⚠️ Se o modelo não existir no CMDB

Esse é um dos problemas mais comuns.

Se aparecer:

```text
m8i.2xlarge
```

mas não existir um objeto correspondente no CMDB, **não invente um GDA-**.

Faça:

1. 📩 peça ao responsável pelo **CMDB** para criar o modelo;
2. informe exatamente o `instance_type`;
3. peça o **objectKey/GDA-** criado;
4. coloque o par no `modelo_servidor_map_aws.yml`;
5. execute um teste;
6. só depois valide a execução completa.

---

## ➕ Quero adicionar um novo campo

Aqui existe uma diferença importante.

### 🟢 Apenas adicionar um novo valor

Exemplo: novo modelo AWS.

Normalmente basta alterar:

```text
modelo_servidor_map_aws.yml
```

### 🟡 Adicionar um campo novo ao CMDB

Exemplo:

```text
Novo campo: Criticidade
```

Nesse caso o trabalho normalmente passa por **duas partes**:

**1. `mapeamento_aws_cmdb.yml`**

Definir o atributo:

```yaml
- id: 12345
  name_assets: "Criticidade"
  chave_cloud: "criticidade_cloud"
  tipo: select
```

**2. Filter Python**

O `cloud_data` precisa realmente produzir:

```python
"criticidade_cloud": valor
```

O filtro percorre os campos de `cloud_data`, procura a `chave_cloud` no mapeamento e monta o payload enviado ao Jira. fileciteturn57file1L482-L494

> 💡 Portanto: **mapeamento diz "onde colocar"; filter diz "qual valor enviar".**

---

## 🧪 Como testar sem sair alterando o CMDB

Use:

```bash
ansible-playbook playbooks/sync_single_aws.yml \
  -e "test_limit=5" \
  -e "dry_run=true"
```

Ou escolha servidores específicos:

```bash
ansible-playbook playbooks/sync_single_aws.yml \
  -e '{"test_servers":["servidor1"]}' \
  -e "dry_run=true"
```

O projeto já possui esses modos de teste documentados no próprio playbook. fileciteturn57file1L71-L84

---

## 🚨 Problemas comuns

| Problema | O que verificar |
|---|---|
| `instance_type` novo | Existe no `modelo_servidor_map_aws.yml`? |
| GDA inexistente | Pedir criação ao time CMDB |
| Campo não aparece | O filter está colocando a chave em `cloud_data`? |
| Campo existe mas não atualiza | Verificar ID do atributo no `mapeamento_aws_cmdb.yml` |
| Servidor foi tratado como novo | Verificar se o `Name` já existe no CMDB |
| EKS entrou no fluxo | Verificar as tags do cluster |
| Credencial Jira falhou | `jira_user` e `jira_password` |
| Muitas alterações inesperadas | Primeiro usar `dry_run=true` |

---

## 📌 Regra de ouro para manutenção

**Não altere o Python para simplesmente cadastrar um novo modelo.**

Para um novo modelo:

```text
AWS instance_type
      ↓
CMDB cria Modelo de Servidor
      ↓
CMDB fornece GDA-XXXXXXX
      ↓
modelo_servidor_map_aws.yml
      ↓
Teste
      ↓
Produção
```

Isso mantém o código simples e evita colocar IDs do CMDB diretamente no Python.
