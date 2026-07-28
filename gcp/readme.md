# integration_assets_gcp

Sincronização de inventário **Google Cloud Platform (GCP)** (via Ansible Automation Platform) para **Jira Assets / CMDB**.

Este é o terceiro membro da família de sync clouds (Azure, AWS, GCP) — segue o **mesmo padrão estrutural e funcional** dos outros dois, com particularidades justificadas do GCP preservadas.

---

## Arquitetura

```text
AAP (inventário GCP)
      │  host data (labels, machine_type, disks, networkInterfaces...)
      ▼
gcp_cmdb_filters.py           ← transform_gcp_host / batch_transform_gcp_hosts
      │  cloud_data (dict)
      ▼
update_asset_gcp              ← consome object_attribute_map
      │  payload Jira Assets
      ▼
POST /object/create  |  PUT /object/{id}  |  deactivate
```

### Comparação com Azure e AWS

|                       | Azure                    | AWS                      | GCP                      |
|-----------------------|--------------------------|--------------------------|--------------------------|
| Variável de tamanho   | `virtual_machine_size`   | `instance_type`          | `machine_type`           |
| Specs (CPU/RAM)       | `azure_vm_specs`         | `aws_vm_specs`           | `gcp_machine_specs`      |
| Mapa GDA              | `modelo_servidor_map`    | `modelo_servidor_map`    | `modelo_servidor_map`    |
| Owner                 | Ambiente + SO + owner_ids | Ambiente + SO + owner_ids | Ambiente + SO + owner_ids |
| Skip cluster          | AKS                       | EKS                       | GKE                       |
| Filter shortname      | `azure_vm_name`           | tag Name                  | `host.name`               |

## Estrutura de arquivos

```text
playbooks/
├── setup_webhook.yml               # [particularidade GCP] Pub/Sub → Cloud Fn → AAP
├── sync_gcp_cmdb.yml               # sync completo (equivalente sync_aws_cmdb.yml)
└── sync_single_gcp.yml             # sync teste com lista/limite/dry-run

files/
└── service_account.json            # [particularidade GCP] necessário para setup_webhook

roles/integration_assets_gcp/
├── filter_plugins/
│   └── gcp_cmdb_filters.py         # transform / batch / update_asset_gcp
├── tasks/
│   ├── main.yml                    # 5 fases (coleta, comparar, criar, skip, deactivate)
│   ├── create.yml                  # POST /object/create
│   ├── deactivate.yml              # PUT status = Desativado
│   └── manage_network_interface.yml # cria/reutiliza Interface de Rede
└── vars/
    ├── main.yml                    # AAP/Jira, IDs, proxy
    ├── mapeamento_gcp_cmdb.yml     # chave_cloud → id do atributo
    └── modelo_servidor_map_gcp.yml # modelo_servidor_map + gcp_machine_specs + owner_ids + cpu_platform_map

README.md
```

## Particularidades do GCP (justificativa)

### 1. `playbooks/setup_webhook.yml` + `files/service_account.json`

Configura o mecanismo **real-time** do GCP: Compute Engine → Logging Sink → Pub/Sub → Cloud Function → AAP. Isso não tem equivalente direto em Azure/AWS nesta base. É executado **uma única vez** para instalar o webhook.

- **Chamadas `gcloud` que permanecem** (todas exclusivamente dentro de `setup_webhook.yml`):
  - `gcloud auth activate-service-account` — autenticação inicial (usa `service_account.json`).
  - `gcloud services enable pubsub / cloudfunctions / cloudbuild` — habilita APIs.
  - `gcloud pubsub topics create/describe` — cria/valida o tópico.
  - `gcloud logging sinks create/describe` — cria o sink de eventos EC-Compute.
  - `gcloud pubsub topics add-iam-policy-binding` — permite ao sink publicar.
  - `gcloud functions deploy` — publica a Cloud Function que dispara o AAP.

Nenhuma dessas chamadas ocorre durante o **sync normal**. O sync obtém 100% dos dados do inventário AAP.

### 2. Nenhuma consulta `gcloud` durante o sync

O inventário AAP GCP já fornece: `name`, `machine_type`, `zone`, `project`, `labels`, `status`, `disks[]`, `networkInterfaces[]`, `cpuPlatform`, `id`. Portanto foram **removidas**:
- `gcloud compute instances describe` (dados vinham daqui — agora vêm do AAP)
- `gcloud compute machine-types describe` (CPU/RAM agora vêm de `gcp_machine_specs`)
- `gcloud compute instances list` (usa API do AAP)

## Playbooks

### `sync_gcp_cmdb.yml` — sync completo
```bash
JIRA_USER=user JIRA_PASSWORD=senha \
  ansible-playbook playbooks/sync_gcp_cmdb.yml -e "sync_mode=full"
```

### `sync_single_gcp.yml` — teste
```bash
# Por lista
ansible-playbook playbooks/sync_single_gcp.yml \
  -e 'test_servers=["apigee-mig-prod-us-east-4-h29c"]'

# Por limite + dry-run
ansible-playbook playbooks/sync_single_gcp.yml -e "test_limit=5" -e "dry_run=true"
```

### `setup_webhook.yml` — (opcional, uma vez)
```bash
ansible-playbook playbooks/setup_webhook.yml \
  -e "gcp_project=clarobrasilx" \
  -e "aap_webhook_url=https://aap.claro.com.br/api/v2/job_templates/XXX/launch/"
```

## Regras de exclusão (skip)

O filter descarta automaticamente:
- Hosts com `enabled=false` no AAP
- **Nós GKE** (labels `goog-gke-*` / `goog-k8s-*`, ou tags `gke-*`)
- Hosts sem a label `ef_cmdb`

## Campos populados no CMDB

| Atributo (id)              | Origem                                                                 |
|----------------------------|------------------------------------------------------------------------|
| Name (1104)                | `host.name`                                                            |
| FQDN (3343)                | `{name}.{zone}.c.{project}.internal`                                   |
| Sistema Operacional (3358) | `disks[0].licenses[0]` (heurística Linux/Windows/Unix)                 |
| Modelo do Servidor (15656) | `machine_type` → `modelo_servidor_map` → `GDA-*`                       |
| **CPU Count (3359)**       | `gcp_machine_specs[machine_type].cpu`                                  |
| **CPU (Platform) (3527)**  | `host.cpuPlatform` → `cpu_platform_map[...]` → objectId (Ref 232)      |
| **Memória RAM (6840)**     | `gcp_machine_specs[machine_type].memory_gb * 1024` (arredondado)       |
| **Owner (3381)**           | Ambiente + SO + `owner_ids` → `USR-<id>`                               |
| Ambiente (1922)            | label `ef_ambiente`                                                    |
| Sistema (9219)             | label `ef_cmdb` (objectKey `GDA-*`)                                    |
| Interface de Rede (3528)   | `networkInterfaces[].networkIP` / `accessConfigs[].natIP`              |
| Status (2957)              | `host.status` → CMDB status                                            |
| Datacenter (3296)          | `Google Cloud` fixo                                                    |
| Tipo de Infraestrutura     | `CLOUD PUBLICA` fixo                                                   |
| Status Discovery (3053)    | `Running` fixo                                                         |
| SOX (9647) / IPE (9648)    | `false` fixo                                                           |
| Disaster Recovery (10677)  | label `ef_recuperacao_de_desastre` / `ef_dr` (fallback `false`)        |
| Grupo Solucionador (7274)  | Windows → `CLBR-TI-INFRA-SUPORTE-WINDOWS` / Linux → `CLBR-TI-INFRA-CLOUD-PUBLIC` |
| Last User (3357)           | `Ansible` fixo                                                         |
| Fornecedor (6829)          | `Google Cloud` fixo                                                    |
| Conta Cloud (10548)        | `host.project` / `host.gcp_project`                                    |
| Capacidade do Disco (3613) | `disks[0].diskSizeGb`                                                  |

## Regra de Owner

**Fonte única**: `Ambiente + Sistema Operacional + owner_ids` (definido em `modelo_servidor_map_gcp.yml`).

| Ambiente | SO      | Owner enviado                             |
|----------|---------|-------------------------------------------|
| Produção | Linux   | `USR-149372` (Luccas Guarnier)            |
| Produção | Windows | `USR-146496` (Carlos Henrique Barboza)    |
| Dev / HML / Sandbox / QA / etc. | qualquer | *(atributo omitido do payload)* |

> **`ef_owner` NÃO participa desta lógica em nenhuma hipótese.**

## Como adicionar um novo `machine_type`

1. Em `vars/modelo_servidor_map_gcp.yml`, dentro de `modelo_servidor_map`:
   ```yaml
   novo-machine-type: GDA-XXXXXXX
   ```
2. Na mesma file, dentro de `gcp_machine_specs`:
   ```yaml
   novo-machine-type:
     cpu: 4
     memory_gb: 16
   ```

Nenhuma alteração no filter Python nem no `mapeamento_gcp_cmdb.yml` é necessária.

## Como habilitar CPU Platform

Em `vars/modelo_servidor_map_gcp.yml`, preencha `cpu_platform_map` com os IDs reais do CMDB (Object Type 232):
```yaml
cpu_platform_map:
  "Intel Broadwell": "000000"
  "Intel Skylake":   "000000"
  # ...
```
Enquanto vazio, o atributo simplesmente não é enviado (não quebra o sync).

## Fluxo create / update / deactivate

- **Create**: servidor em GCP mas não em CMDB → `POST /object/create`.
- **Skip**: servidor já existe no CMDB → não altera (preserva dados manuais).
- **Deactivate**: servidor no CMDB mas não em GCP → `PUT` com status = "Desativado" (apenas se `enable_deactivation: true`).

## Troubleshooting

| Sintoma                        | Causa provável                                                |
|--------------------------------|----------------------------------------------------------------|
| CPU / Memória sem valor        | `machine_type` ausente de `gcp_machine_specs`                  |
| Owner não aparece em Prod      | Label `ef_ambiente` não contém `prod`/`prd`/`production`       |
| Host ignorado                  | Falta label `ef_cmdb` OU é nó GKE (`goog-gke-*`)               |
| Servidor não é criado          | Já existe no CMDB (skip preserva dados manuais)                |
| CPU Platform ausente           | `cpu_platform_map` vazio ou `host.cpuPlatform` não mapeado     |

Ative log detalhado com `-vvv` na chamada `ansible-playbook`.