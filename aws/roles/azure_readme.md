# integration_assets_azure

Sincronização de inventário **Azure** (via Ansible Automation Platform) para **Jira Assets / CMDB**.

Cria, mantém e (opcionalmente) desativa objetos do Object Type `121` (Servidor) no CMDB a partir das VMs Azure descobertas no inventário AAP.

---

## Arquitetura

```text
AAP (inventário Azure)
      │  variables (JSON por host)
      ▼
azure_cmdb_filters.py         ← transform_azure_host / batch_transform_azure_hosts
      │  cloud_data (dict)
      ▼
update_asset_azure            ← consome object_attribute_map
      │  payload Jira Assets
      ▼
POST /object/create  |  PUT /object/{id}  |  deactivate
```

## Estrutura de arquivos

```text
roles/integration_assets_azure/
├── filter_plugins/
│   └── azure_cmdb_filters.py         # Transformações Python
├── tasks/
│   ├── main.yml                      # Orquestração (5 fases)
│   ├── create.yml                    # POST /object/create
│   ├── deactivate.yml                # PUT status = Desativado
│   └── manage_network_interface.yml  # Cria/reutiliza Interface de Rede
└── vars/
    ├── main.yml                      # Credenciais AAP/Jira, IDs, proxy
    ├── mapeamento_azure_cmdb.yml     # chave_cloud → id do atributo
    └── modelo_servidor_map_azure.yml # vm_size → objectKey, azure_vm_specs, owner_ids
```

## Playbooks

- `playbooks/sync_azure_cmdb.yml` — sync completo
- `playbooks/sync_single_azure.yml` — teste (lista/limite/dry-run)

### Como rodar

**Sync completo:**
```bash
JIRA_USER=usuario JIRA_PASSWORD=senha \
  ansible-playbook playbooks/sync_azure_cmdb.yml -e "sync_mode=full"
```

**Teste com lista:**
```bash
ansible-playbook playbooks/sync_single_azure.yml \
  -e 'test_servers=["azlxprd001", "azwinprd002"]'
```

**Teste com limite + dry-run:**
```bash
ansible-playbook playbooks/sync_single_azure.yml \
  -e "test_limit=5" -e "dry_run=true"
```

## Variáveis principais (`vars/main.yml`)

| Variável | Descrição |
|---|---|
| `jira_url` | URL do Jira Assets API |
| `jira_user` / `jira_password` | Credenciais (via env `JIRA_USER` / `JIRA_PASSWORD`) |
| `aap_host` / `aap_inventory_id` / `aap_token` | Conexão com AAP |
| `object_type_id_servidor` | `121` |
| `object_type_id_interface_rede` | `230` |
| `sync_mode` | `full` \| `create` \| `deactivate` |
| `enable_deactivation` | `true`/`false` |
| `proxy_env` | Proxy corporativo |

## Regras de exclusão (skip)

O filter descarta automaticamente:
- Hosts com `enabled=false` no AAP
- Nós de cluster AKS (heurística: `resource_group` inicia com `MC_`, tags `aks-managed-*`, ou `orchestrator=kubernetes`)
- Hosts sem a tag `ef_cmdb`

## Campos populados no CMDB

| Atributo (id) | Origem |
|---|---|
| Name (1104) | `azure_vm_name` / `host.name` |
| FQDN (3343) | `public_dns_hostnames[0]` ou `name-vmid` |
| Sistema Operacional (3358) | `os_disk.operating_system_type` / `image.offer` |
| Modelo do Servidor (15656) | `virtual_machine_size` → `modelo_servidor_map` → `GDA-*` |
| **CPU Count (3359)** | `azure_vm_specs[vm_size].cpu` |
| **Memória RAM (6840)** | `azure_vm_specs[vm_size].memory_gb * 1024` (em Mb) |
| **Owner (3381)** | Ambiente + SO + `owner_ids` → `USR-<id>` |
| Ambiente (1922) | tag `ef_ambiente` |
| Sistema (9219) | tag `ef_cmdb` (objectKey) |
| Interface de Rede (3528) | IPs privados/públicos |
| Status (2957) | Azure `powerstate` → CMDB status |
| Datacenter (3296) | `Azure` fixo |
| Tipo de Infraestrutura (9948) | `CLOUD PUBLICA` fixo |
| Status Discovery (3053) | `Running` fixo |
| SOX (9647) / IPE (9648) | `false` fixo |
| Disaster Recovery (10677) | tag `ef_recuperacao_de_desastre` / `ef_dr` |
| Grupo Solucionador - Infra (7274) | Windows → `CLBR-TI-INFRA-SUPORTE-WINDOWS` / Linux → `CLBR-TI-INFRA-CLOUD-PUBLIC` |
| Last User (3357) | `Ansible` fixo |
| Fornecedor (6829) | `Azure` fixo |
| Conta Cloud (10548) | `resource_group` |

## Regra de Owner

Fonte única: **Ambiente + Sistema Operacional + `owner_ids`** (em `modelo_servidor_map_azure.yml`).

| Ambiente | SO | Owner enviado |
|---|---|---|
| Produção | Linux | `USR-149372` (Luccas Guarnier) |
| Produção | Windows | `USR-146496` (Carlos Henrique Barboza) |
| Dev / HML / Sandbox / QA / etc. | qualquer | *(atributo omitido do payload)* |

> `ef_owner` **é ignorado** por design nesta sincronização.

## Como adicionar um novo `virtual_machine_size`

1. Em `vars/modelo_servidor_map_azure.yml`, dentro de `modelo_servidor_map`:
   ```yaml
   Standard_XX_v9: GDA-XXXXXXX
   ```
2. Na mesma file, dentro de `azure_vm_specs`:
   ```yaml
   Standard_XX_v9:
     cpu: 8
     memory_gb: 32
   ```

Nenhuma alteração no filter Python nem no `mapeamento_azure_cmdb.yml` é necessária.

## Troubleshooting

| Sintoma | Causa provável |
|---|---|
| CPU / Memória não aparece no CMDB | `vm_size` ausente de `azure_vm_specs` |
| Owner não aparece em VM Prod | Tag `ef_ambiente` não contém `prod`/`prd`/`production` |
| Host ignorado | Falta tag `ef_cmdb` OU é nó AKS (RG começa com `MC_`) |
| Servidor não é criado | Já existe no CMDB (política: skip para preservar dados manuais) |

Ative o log detalhado com `-vvv` na chamada `ansible-playbook`.