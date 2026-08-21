# ☁️ Azure → CMDB | Sincronização de Servidores

> **Objetivo:** manter as VMs Azure refletidas no **Jira Assets (CMDB)** usando **AAP (Ansible Automation Platform)**.

![Status](https://img.shields.io/badge/status-ativo-brightgreen)
![Cloud](https://img.shields.io/badge/cloud-Azure-0078D4)
![Automation](https://img.shields.io/badge/automation-AAP-red)

## 🧭 Em poucas palavras

O projeto funciona como uma ponte:

**Azure → AAP → tratamento dos dados → CMDB**

A automação consulta as VMs, transforma os dados e compara com o CMDB.

| Situação | Ação |
|---|---|
| 🆕 VM não existe | **CRIAR** |
| 🔄 VM existe, foi criada pelo Ansible e o modelo mudou | **ATUALIZAR** |
| 🟢 VM já está correta | **SKIP** |
| ♻️ VM voltou depois de estar desativada | **REATIVAR** |
| 🔴 VM não existe mais no Azure e foi criada pelo Ansible | **DESATIVAR** |
| 🛡️ Nó AKS | **Protegido** |

O fluxo principal está em `playbooks/sync_azure_cmdb.yml`. fileciteturn57file0L5-L12

---

## 🔄 Visão simples

```text
        Azure
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

O filtro também identifica nós AKS para evitar que eles sejam tratados como VMs comuns. fileciteturn57file0L433-L460

---

## 🧩 Onde adicionar novos modelos

Arquivo:

```text
roles/integration_assets_azure/vars/modelo_servidor_map_azure.yml
```

A tradução é:

```text
Azure vm_size → GDA do Modelo de Servidor
```

Exemplo:

```yaml
modelo_servidor_map:
  Standard_B2ms: GDA-3224000
  Standard_D4s_v3: GDA-3224001
```

O projeto foi estruturado justamente para que novos `vm_size` sejam adicionados nesse arquivo, sem alterar o filter Python ou o `mapeamento_azure_cmdb.yml`. fileciteturn57file0L2307-L2325

### 🆕 Novo modelo

Imagine que o Azure comece a usar:

```text
Standard_D16s_v6
```

Primeiro:

1. 📩 peça ao time de **CMDB** para criar o modelo;
2. passe `Standard_D16s_v6`;
3. receba o `GDA-XXXXXXX`;
4. adicione:

```yaml
modelo_servidor_map:
  Standard_D16s_v6: GDA-XXXXXXX
```

5. teste;
6. valide a sincronização.

### ⚠️ Modelo não existe no CMDB

**Não coloque um GDA inventado.**

Se o modelo não existir, peça ao responsável pelo CMDB:

> "Preciso cadastrar o modelo `Standard_D16s_v6` no Object Type Modelo de Servidor (406) e me passar o objectKey/GDA gerado."

Depois basta colocar o GDA no mapa.

---

## 🧠 CPU e memória são outra coisa

O modelo do servidor é uma informação.

CPU e memória vêm de outro mapa:

```yaml
azure_vm_specs:
  Standard_B2ms:
    cpu: 2
    memory_gb: 8
```

Portanto, se aparecer um novo `vm_size`, normalmente verifique **os dois mapas**:

```text
modelo_servidor_map_azure.yml
        ↓
Modelo do Servidor

azure_vm_specs
        ↓
CPU + Memória
```

---

## ➕ Adicionando um novo campo

Para um campo novo do CMDB, normalmente é necessário:

### 1. Definir o atributo

Em:

```text
roles/integration_assets_azure/vars/mapeamento_azure_cmdb.yml
```

Exemplo:

```yaml
- id: 12345
  name_assets: "Criticidade"
  chave_cloud: "criticidade_cloud"
  tipo: select
```

### 2. Fazer o filter produzir o valor

O `cloud_data` precisa conter:

```python
"criticidade_cloud": valor
```

O filtro procura cada campo no `object_attribute_map` e transforma o valor para o formato aceito pelo CMDB. fileciteturn57file0L366-L369

> 💡 **Mapping = onde fica no CMDB. Filter = de onde vem o valor.**

---

## 🧪 Teste seguro

Para testar alguns servidores:

```bash
ansible-playbook playbooks/sync_single_azure.yml \
  -e "test_limit=5" \
  -e "dry_run=true"
```

Ou por nome:

```bash
ansible-playbook playbooks/sync_single_azure.yml \
  -e 'test_servers=["srv01","srv02"]' \
  -e "dry_run=true"
```

Esses modos já fazem parte do playbook de teste. fileciteturn57file0L62-L83

---

## 🚨 Problemas comuns

| Sintoma | Verifique |
|---|---|
| `vm_size` novo | Está no `modelo_servidor_map_azure.yml`? |
| GDA não encontrado | Solicitar cadastro ao CMDB |
| CPU/RAM vazios | Está no `azure_vm_specs`? |
| Campo novo não aparece | Filter produz a `chave_cloud`? |
| VM AKS foi processada | Verificar tags/resource group AKS |
| Credencial falhou | `jira_user` / `jira_password` |
| Mudanças inesperadas | Executar primeiro com `dry_run=true` |

---

## 📌 Regra de ouro

Para um **novo modelo Azure**:

```text
Azure vm_size
     ↓
CMDB cria modelo
     ↓
CMDB entrega GDA-XXXXXXX
     ↓
modelo_servidor_map_azure.yml
     ↓
azure_vm_specs (se necessário)
     ↓
Teste
     ↓
Produção
```

Não coloque regra específica de modelo dentro do Python se ela puder ser resolvida pelo arquivo de variáveis.
