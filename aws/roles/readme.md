# integration_assets_aws

Sincronização de inventário **AWS** (via Ansible Automation Platform) para **Jira Assets / CMDB**.

Cria, mantém e (opcionalmente) desativa objetos do Object Type `121` (Servidor) no CMDB a partir das instâncias EC2 descobertas no inventário AAP.

---

## Arquitetura

```text
AAP (inventário AWS)
      │  variables (JSON por host)
      ▼
aws_cmdb_filters.py           ← transform_aws_host / batch_transform_aws_hosts
      │  cloud_data (dict)
      ▼
update_asset (mesmo filter)   ← consome object_attribute_map
      │  payload Jira Assets
      ▼
POST /object/create  |  PUT /object/{id}  |  deactivate
```

## Estrutura de arquivos

```text
roles/integration_assets_aws/
├── filter_plugins/
│   └── aws_cmdb_filters.py         # Transformações Python (host → cloud_data → payload)
├── tasks/
│   ├── main.yml                    # Orquestração (5 fases)
│   ├── create.yml                  # POST /object/create
│   └── deactivate.yml              # PUT status = Desativado
└── vars/
    ├── main.yml                    # Credenciais AAP/Jira, IDs, proxy
    ├── mapeamento_aws_cmdb.yml     # chave_cloud → id do atributo no CMDB
    └── modelo_servidor_map_aws.yml # instance_type → objectKey, aws_vm_specs, owner_ids
```

## Playbooks

- `playbooks/sync_aws_cmdb.yml` — sync completo do inventário
- `playbooks/sync_single_aws.yml` — teste com lista de nomes ou N primeiros

### Como rodar

**Sync completo:**
```bash
JIRA_USER=usuario JIRA_PASSWORD=senha \
  ansible-playbook playbooks/sync_aws_cmdb.yml -e "sync_mode=full"
```

**Teste com lista de servidores:**
```bash
ansible-playbook playbooks/sync_single_aws.yml \
  -e 'test_servers=["i-abc.sa-east-1.compute.internal"]'
```

**Teste com limite + dry-run:**
```bash
ansible-playbook playbooks/sync_single_aws.yml \
  -e "test_limit=5" -e "dry_run=true"
```

## Variáveis principais (`vars/main.yml`)

| Variável | Descrição |
|---|---|
| `jira_url` | URL do Jira Assets API |
| `jira_user` / `jira_password` | Credenciais (via env `JIRA_USER` / `JIRA_PASSWORD`) |
| `aap_host` / `aap_inventory_id` / `aap_token` | Conexão com AAP |
| `object_type_id_servidor` | `121` (Servidor no CMDB) |
| `sync_mode` | `full` \| `create` \| `deactivate` |
| `enable_deactivation` | `true`/`false` |
| `proxy_env` | Proxy corporativo |

## Regras de exclusão (skip)

O filter descarta automaticamente:
- Hosts com `enabled=false` no AAP
- Nós de cluster EKS (heurística: `iam_instance_profile.arn` contém `:instance-profile/eks-`, ou tags `aws:eks:*`, `eks:cluster-name`, `kubernetes.io/cluster/*`)
- Hosts sem a tag `ef_cmdb`

## Campos populados no CMDB

| Atributo (id) | Origem |
|---|---|
| Name (1104) | `instance_id.region.compute.internal` |
| FQDN (3343) | `private_dns_name` |
| Sistema Operacional (3358) | `platform` / `platform_details` (Windows/Linux) |
| Modelo do Servidor (15656) | `instance_type` → `modelo_servidor_map` → `GDA-*` |
| **CPU Count (3359)** | `aws_vm_specs[instance_type].cpu` (fallback: `cpu_options.core_count * threads_per_core`) |
| **Memória RAM (6840)** | `aws_vm_specs[instance_type].memory_gb * 1024` (em Mb, com `round` para floats) |
| **Owner (3381)** | Ambiente + SO + `owner_ids` → `USR-<id>` |
| Ambiente (1922) | tags `ef_ambiente` / `environment` |
| Sistema (9219) | tag `ef_cmdb` (objectKey) |
| Interface de Rede (3528) | IPs privado/público |
| Status (2957) | AWS `state` → CMDB status |
| Datacenter (3296) | `AWS` fixo |
| Tipo de Infraestrutura (9948) | `CLOUD PUBLICA` fixo |
| Status Discovery (3053) | `Running` fixo |
| SOX (9647) / IPE (9648) | `false` fixo |
| Disaster Recovery (10677) | tag `ef_recuperacao_de_desastre` / `ef_dr` (fallback `false`) |
| Grupo Solucionador - Infra (7274) | Windows → `CLBR-TI-INFRA-SUPORTE-WINDOWS` / Linux → `CLBR-TI-INFRA-CLOUD-PUBLIC` |
| Last User (3357) | `Ansible` fixo |
| Fornecedor (6829) | `AWS` fixo |
| Conta Cloud (10548) | `account_id` / `owner_id` |

## Regra de Owner

Fonte única: **Ambiente + Sistema Operacional + `owner_ids`** (em `modelo_servidor_map_aws.yml`).

| Ambiente | SO | Owner enviado |
|---|---|---|
| Produção | Linux | `USR-149372` (Luccas Guarnier) |
| Produção | Windows | `USR-146496` (Carlos Henrique Barboza) |
| Dev / HML / Sandbox / QA / Test / etc. | qualquer | *(atributo omitido do payload)* |

> `ef_owner` **não participa** desta lógica.

## Como adicionar um novo `instance_type`

1. Em `vars/modelo_servidor_map_aws.yml`, dentro de `modelo_servidor_map`:
   ```yaml
   novo.type: GDA-XXXXXXX
   ```
2. Na mesma file, dentro de `aws_vm_specs`:
   ```yaml
   novo.type:
     cpu: 4
     memory_gb: 16
   ```

Nenhuma alteração no filter Python nem no `mapeamento_aws_cmdb.yml` é necessária.

## Troubleshooting

| Sintoma | Causa provável |
|---|---|
| CPU / Memória não aparece no CMDB | `instance_type` ausente de `aws_vm_specs` |
| Owner não aparece em VM Prod | Tag `ef_ambiente` não contém `prod`/`prd`/`production` |
| Host ignorado | Falta tag `ef_cmdb` OU é nó EKS |
| Servidor não é criado | Já existe no CMDB (política: skip para preservar dados manuais) |

Ative o log detalhado com `-vvv` na chamada `ansible-playbook`.