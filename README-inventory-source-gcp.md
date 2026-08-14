# 🔌 Inventory Source GCP

## 🎯 O que este projeto faz?

Ele atualiza automaticamente o Inventory Source GCP com os projetos que possuem:

```text
Compute API = ENABLED
```

```text
Todos os projetos GCP
        ↓
Compute API?
        ↓
somente ENABLED
        ↓
Inventory Source #652
```

---

## 1. 🔑 Configuração

Trecho real:

```yaml
inventory_source_id: "652"
jt_id: "698"

controller_host: "https://aap.claro.com.br"

trigger_sync: true
exclude_projects: []

quota_project: "claro-infracloud"
```

Então temos:

```text
Inventory Source → 652
Job Template     → 698
Quota Project    → claro-infracloud
```

---

## 2. 🔐 Credential

O projeto espera:

```text
GOOGLE_APPLICATION_CREDENTIALS
```

E verifica se o arquivo existe.

Depois executa:

```yaml
gcloud auth activate-service-account
--key-file={{ lookup('env', 'GOOGLE_APPLICATION_CREDENTIALS') }}
--project={{ quota_project }}
```

Então:

```text
AAP Credential
 ↓
JSON da Service Account
 ↓
GOOGLE_APPLICATION_CREDENTIALS
 ↓
gcloud
```

---

## 3. 🌎 Descobrir projetos

O código executa:

```bash
gcloud projects list --format=value(projectId)
```

Depois verifica:

```bash
gcloud services list \
  --project={{ item }} \
  --filter="name:compute.googleapis.com"
```

Resultado:

```text
Projeto
 ↓
Compute API?
 ├── ENABLED → entra
 └── DISABLED → ignora
```

---

## 4. 🚫 Exclusões

Existe:

```yaml
exclude_projects: []
```

Então o fluxo é:

```text
projetos com Compute
        ↓
exclude_projects
        ↓
final_projects
```

---

## 5. 📦 Atualização do Inventory Source

O source usa:

```yaml
plugin: google.cloud.gcp_compute
auth_kind: serviceaccount
projects: []

filters:
  - status = RUNNING

hostnames:
  - name
```

Depois o playbook preenche `projects` com a lista descoberta.

---

## 6. 🌐 Dados dos hosts

Trecho real:

```yaml
compose:
  ansible_host: networkInterfaces[0].accessConfigs[0].natIP
    | default(networkInterfaces[0].networkIP, true)

  private_ip: networkInterfaces[0].networkIP
  public_ip: networkInterfaces[0].accessConfigs[0].natIP
  machine_type: machineType | basename
  zone: zone | basename
  gcp_project: project | basename
  gcp_labels: labels | default({})
```

---

## 7. 🏷️ Grupos

```yaml
keyed_groups:
  - key: zone | basename
    prefix: Zona

  - key: gcp_project
    prefix: Projeto

  - key: gcp_labels.ef_ambiente | default('SEM_EF_AMBIENTE')
    prefix: Ambiente

  - key: gcp_labels.ef_cmdb | default('SEM_EF_CMDB')
    prefix: Sistema
```

---

## 8. 🔄 Também atualiza o Job Template

Além do Inventory Source:

```text
Inventory Source #652
        +
Job Template #698
```

A lista de projetos descoberta é usada nos dois.

```text
projetos encontrados
       ├──────────────► Inventory Source #652
       │
       └──────────────► Job Template #698
```

---

## 9. ▶️ Sync

Como:

```yaml
trigger_sync: true
```

o projeto pode disparar:

```text
POST /inventory_sources/652/update/
```

Depois da atualização:

```text
Inventory Source
      ↓
sync
      ↓
AAP Inventory
```

---

## 🧠 Resumo

```text
GCP Projects
 ↓
Compute API ENABLED
 ↓
exclude_projects
 ↓
final_projects
 ├──→ Inventory Source #652
 └──→ Job Template #698
           ↓
         sync
```
