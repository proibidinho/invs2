#!/usr/bin/env python3
"""
collect_metrics.py — Coletor + calculadora de métricas AAP Controller.

Refatoração v3 (histórico + multi-organização):

  Continua usando SOMENTE a API do Controller (tokens/jobs/job_host_summaries/
  instances/ping), igual às versões anteriores. Não usa analytics/job_explorer.

  Mudanças em relação à versão anterior (quick_metrics/top_30/curation_*):

    * Histórico persistente em disco (--history-dir), com no máximo
      --max-history-days (730) dias retidos. Primeira execução faz carga
      inicial de até 730 dias; execuções seguintes fazem coleta incremental
      (busca só a janela nova + um overlap de alguns dias, para pegar jobs
      que ainda estavam "running"/"pending" na coleta anterior).

    * Sem filtro de organização por padrão: coleta todos os jobs da janela
      e separa por organização internamente (mais barato que uma chamada
      por org) e monta também a visão agregada "ALL". --org continua
      disponível para uso manual/pontual (compatibilidade), mas o dataset
      de produção (dashboard_data.json) é sempre multi-org.

    * Métricas por Job Template para TODOS os templates (não só o top 30).
      success_rate é sempre percentual (0-100), nunca fração 0-1. Não há
      mais campo "successful" nem "impact" nem "failure_rate" (a menos que
      seja tecnicamente necessário) nem classificação de severidade.

    * hosts_impacted = união de hosts ÚNICOS por template no período
      (não soma de host_count por execução). Jobs 100% em localhost
      colapsam para hosts_impacted = 1 (normalização de nome de host).

    * host_data_coverage: recalculado considerando SOMENTE jobs do tipo
      "job" (execução de playbook) — project_update/inventory_update/
      workflow_job/system_job legitimamente não têm job_host_summaries,
      então não devem ser contados como "cobertura baixa".

    * curadoria = TODOS os templates com success_rate < 90% (não só top 30).
      O Python só fornece os números; a classificação visual (faixas de
      gravidade) fica a cargo do Grafana.

    * mapa de curadoria = exatamente os templates da curadoria, eixos
      execuções (X) × falhas (Y). Sem "impact" inventado.

    * top_30 = por número de execuções, com consolidação de todo template
      cujo nome comece com "escondida" em "Escondida* (consolidado)".
      Essa consolidação NÃO afeta a lista de curadoria/templates completos.

    * "período" no dashboard = conjunto fixo pré-calculado (7d/14d/30d/3m/
      6m/1y/all), igual aos valores que já existiam em PERIOD_DAYS. Para
      cada organização (+ ALL), o JSON final já traz summary/templates/
      top_30/curadoria calculados para cada um desses períodos, então o
      Grafana troca de período/organização sem re-executar o coletor.
      (hosts_impacted é uma contagem única — não dá para recalcular a
      partir de somas diárias — por isso os períodos são pré-calculados
      a partir dos jobs individuais, e não de um seletor de datas livre.)

    * trend = série diária única por organização, cobrindo todo o
      histórico retido (até 730 dias). O próprio Grafana filtra por data
      usando o time range do painel — não precisa de uma cópia por período.

    * platform_health = estrutura pequena e normalizada (controller +
      execution_nodes), não o payload bruto de /instances/, /ping/,
      /dashboard/. "Fila" (queue) só existe de forma agregada e global
      no Controller (contagem de jobs pending/waiting) — a API não expõe
      fila por Execution Node específico, então não inventamos uma
      fórmula por nó; expomos só o total global.

    * failure_causes (stdout dos jobs falhos): desativado nesta versão,
      conforme solicitado. Pode voltar quando houver amostra real de
      stdout para calibrar o parser.

    * Só jobs em status terminal (successful/failed/error) entram nas
      métricas — running/pending/waiting/new/canceled são ignorados nos
      agregados (mas continuam salvos no histórico com seu status real,
      até chegarem a um estado terminal numa execução futura).

    * platform_health.cluster_capacity_health_pct: % de saúde do cluster
      inteiro, calculado somando capacity e consumed_capacity de todos os
      nós (controller + execution nodes) — não a média simples dos % de
      cada nó — para ponderar corretamente nós com capacidades diferentes.

Fontes de API usadas (Controller):
  - POST /api/controller/v2/tokens/
  - GET  /api/controller/v2/organizations/
  - GET  /api/controller/v2/jobs/
  - GET  /api/controller/v2/jobs/{id}/job_host_summaries/
  - GET  /api/controller/v2/instances/
  - GET  /api/controller/v2/ping/

Uso típico:
  # primeira execução (carga histórica inicial de até 730 dias)
  python collect_metrics.py

  # execução diária (atualização incremental do histórico)
  python collect_metrics.py

  # uso manual/pontual, uma única organização, sem tocar no histórico
  python collect_metrics.py --org 98 --period 30d --no-history
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean

from dotenv import load_dotenv

load_dotenv()

try:
    import requests
except ImportError:
    sys.exit("Falta a lib requests. Rode: pip install requests")

import urllib3


# --------------------------------------------------------------------------
# Períodos fixos pré-calculados no dataset final (decisão alinhada com o
# usuário: dropdown de períodos fixos, não seletor de data livre).
# --------------------------------------------------------------------------
PERIOD_DAYS = {
    "7d": 7,
    "14d": 14,
    "30d": 30,
    "3m": 90,
    "6m": 180,
    "1y": 365,
    "all": None,  # todo o histórico retido (até MAX_HISTORY_DAYS)
}

MAX_HISTORY_DAYS = 730
DEFAULT_OVERLAP_DAYS = 3  # reconsulta esses últimos dias a cada execução incremental
JOB_TYPES_WITH_HOSTS = {"job"}  # só execuções de playbook têm job_host_summaries

# Só jobs em estado terminal entram nas métricas (execuções/success_rate/
# duração/hosts/tendência). O coletor roda 1x/dia buscando o dia anterior,
# então "running"/"pending"/"waiting"/"new" não deveriam aparecer no recorte
# do dia anterior — mas se aparecerem (job muito longo, atraso, etc.), não
# devem poluir as métricas. "canceled" também fica de fora: não é sucesso
# nem falha de execução, é uma interrupção manual.
TERMINAL_STATUSES = {"successful", "failed", "error"}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser(
        description="Coleta e calcula métricas operacionais do AAP Controller"
    )

    # Conexão (preservado sem alterações de compatibilidade)
    p.add_argument("--url", default=os.environ.get("AAP_URL", ""))
    p.add_argument("--username", default=os.environ.get("AAP_USERNAME", ""))
    p.add_argument("--password", default=os.environ.get("AAP_PASSWORD", ""))
    p.add_argument("--token", default=os.environ.get("AAP_TOKEN", ""),
                    help="Se informado, pula o POST /tokens/ e usa este token direto.")
    p.add_argument("--proxy", default=os.environ.get("AAP_PROXY", ""))
    p.add_argument(
        "--insecure",
        action="store_true",
        default=os.environ.get("AAP_INSECURE", "true").lower() == "true",
    )

    # Modo de operação
    p.add_argument(
        "--org",
        default=os.environ.get("AAP_ORG", ""),
        help="Uso manual/pontual: filtra a coleta por uma única organização "
             "(nome ou ID) e ignora o histórico multi-org. Vazio (padrão) = "
             "coleta todas as organizações e atualiza o histórico normalmente.",
    )
    p.add_argument(
        "--period",
        choices=list(PERIOD_DAYS.keys()),
        default=os.environ.get("AAP_PERIOD", "all"),
        help="Usado apenas no modo --org manual (fora do fluxo de histórico), "
             "para escolher a janela daquela consulta pontual.",
    )
    p.add_argument("--no-history", action="store_true",
                    help="Não lê nem grava o histórico em disco; roda como consulta pontual "
                         "(equivalente ao comportamento antigo). Útil combinado com --org/--period.")

    # Histórico
    p.add_argument("--history-dir", default=os.environ.get("AAP_HISTORY_DIR", "./history"))
    p.add_argument("--max-history-days", type=int,
                    default=int(os.environ.get("AAP_MAX_HISTORY_DAYS", str(MAX_HISTORY_DAYS))))
    p.add_argument("--overlap-days", type=int,
                    default=int(os.environ.get("AAP_OVERLAP_DAYS", str(DEFAULT_OVERLAP_DAYS))),
                    help="Em coleta incremental, quantos dias para trás reconsultar para "
                         "pegar jobs que ficaram 'running'/'pending' na coleta anterior.")

    # Paginação / performance
    p.add_argument("--page-size", type=int,
                    default=int(os.environ.get("AAP_PAGE_SIZE", "200")))
    p.add_argument("--host-page-size", type=int,
                    default=int(os.environ.get("AAP_HOST_PAGE_SIZE", "200")))
    p.add_argument("--skip-host-summaries", action="store_true")
    p.add_argument(
        "--max-host-summary-jobs",
        type=int,
        default=int(os.environ.get("AAP_MAX_HOST_SUMMARY_JOBS", "0")),
        help="Limita quantos jobs (dentre os NOVOS desta execução) recebem consulta de "
             "job_host_summaries. 0 = todos os elegíveis (tipo 'job').",
    )

    p.add_argument("--output-dir", default=os.environ.get("AAP_OUTPUT_DIR", "./saida"))

    return p.parse_args()


# --------------------------------------------------------------------------
# Datas
# --------------------------------------------------------------------------
def today_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def days_ago_str(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")


def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_date_only(value):
    dt = parse_dt(value)
    return dt.date().isoformat() if dt else None


# --------------------------------------------------------------------------
# Cliente AAP (inalterado — preserva autenticação, token, proxy, SSL, paginação)
# --------------------------------------------------------------------------
class AAP:
    def __init__(self, url, username, password, token, proxy, insecure):
        self.url = url.rstrip("/")
        self.verify = not insecure
        self.session = requests.Session()

        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})

        if insecure:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        self.token = token or self._get_token(username, password)
        self.session.headers.update(
            {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        )

    def _get_token(self, username, password):
        r = self.session.post(
            f"{self.url}/api/controller/v2/tokens/",
            auth=(username, password),
            verify=self.verify,
            timeout=60,
        )
        r.raise_for_status()
        token = r.json().get("token")
        if not token:
            raise RuntimeError(f"Token não retornado. HTTP {r.status_code}: {r.text[:300]}")
        print("[auth] token obtido com sucesso")
        return token

    def get(self, path, params=None):
        r = self.session.get(f"{self.url}{path}", params=params, verify=self.verify, timeout=120)
        r.raise_for_status()
        return r.json()


def resolve_organization(aap, org):
    """Aceita nome ou ID da organização. Retorna (org_id, org_name) ou (None, None)."""
    if not org:
        return None, None

    if str(org).isdigit():
        data = aap.get(f"/api/controller/v2/organizations/{org}/")
        return data["id"], data["name"]

    data = aap.get("/api/controller/v2/organizations/", {"name__iexact": org, "page_size": 5})
    results = data.get("results", [])

    if not results:
        sys.exit(f"Organização '{org}' não encontrada.")
    if len(results) > 1:
        nomes = ", ".join(r["name"] for r in results)
        sys.exit(f"Mais de uma organização encontrada para '{org}': {nomes}. Use o ID.")

    return results[0]["id"], results[0]["name"]


# --------------------------------------------------------------------------
# Coleta de jobs
# --------------------------------------------------------------------------
def collect_jobs(aap, start, end, page_size, org_id=None):
    date_filter = {"created__lte": f"{end}T23:59:59Z", "order_by": "started"}
    if start:
        date_filter["created__gte"] = f"{start}T00:00:00Z"
    if org_id:
        date_filter["organization"] = org_id

    probe = aap.get("/api/controller/v2/jobs/", {**date_filter, "page": 1, "page_size": 1})
    count = int(probe.get("count", 0))
    pages = (count + page_size - 1) // page_size if count else 0

    print(f"[jobs] janela={start or 'inicio'}..{end} | org={org_id or 'todas'} | "
          f"count={count} | páginas={pages} | page_size={page_size}")

    results = []
    for page in range(1, pages + 1):
        data = aap.get("/api/controller/v2/jobs/", {**date_filter, "page": page, "page_size": page_size})
        batch = data.get("results", [])
        results.extend(batch)
        print(f"[jobs] página {page}/{pages} -> +{len(batch)} (total={len(results)})")
        if not data.get("next"):
            break

    return results


def compact_job(job):
    sf = job.get("summary_fields") or {}
    template = sf.get("job_template") or {}
    organization = sf.get("organization") or {}

    started = job.get("started") or job.get("created")

    return {
        "job_id": job.get("id"),
        "job_type": job.get("type", "job"),  # job/project_update/inventory_update/workflow_job/system_job
        "template_id": template.get("id") or job.get("job_template"),
        "template_name": template.get("name") or job.get("name") or "desconhecido",
        "status": job.get("status", "unknown"),
        "created": job.get("created"),
        "started": started,
        "finished": job.get("finished"),
        "elapsed": float(job.get("elapsed") or 0),
        "org_id": job.get("organization") or organization.get("id"),
        "org_name": organization.get("name") or "Sem organização",
        "launch_type": job.get("launch_type", "manual"),
    }


def is_localhost(host_name):
    if not host_name:
        return True
    normalized = host_name.strip().lower()
    return normalized in ("localhost", "127.0.0.1", "::1")


def collect_host_summary(aap, job_id, page_size):
    first = aap.get(f"/api/controller/v2/jobs/{job_id}/job_host_summaries/",
                     {"page": 1, "page_size": page_size})
    total = int(first.get("count", 0))
    pages = (total + page_size - 1) // page_size if total else 0
    rows = list(first.get("results", []))

    for page in range(2, pages + 1):
        data = aap.get(f"/api/controller/v2/jobs/{job_id}/job_host_summaries/",
                        {"page": page, "page_size": page_size})
        rows.extend(data.get("results", []))

    # Normaliza hosts: qualquer variação reconhecida de localhost vira a
    # mesma chave canônica, para que a união de hosts colapse corretamente.
    hosts = set()
    for row in rows:
        host_name = row.get("host_name")
        if not host_name:
            continue
        hosts.add("localhost" if is_localhost(host_name) else host_name)

    return {
        "job_id": job_id,
        "host_count": total,
        "hosts": sorted(hosts),
    }


def collect_controller_health(aap):
    """Coleta bruta de instances/ping + contagem global de jobs pending/waiting.
    A normalização para o formato pequeno do dashboard acontece em build_platform_health().
    """
    health = {}
    for name, path in (
        ("instances", "/api/controller/v2/instances/"),
        ("ping", "/api/controller/v2/ping/"),
    ):
        try:
            health[name] = aap.get(path, {"page": 1, "page_size": 200})
            print(f"[health] {name}: OK")
        except requests.RequestException as exc:
            print(f"[health] {name}: ERRO -> {exc}")
            health[name] = {"error": str(exc)}

    # Fila: a API não expõe fila por Execution Node específico. O que existe
    # de forma confiável é a contagem global de jobs em pending/waiting no
    # cluster inteiro (não é o mesmo que consumed_capacity, que é capacidade
    # em uso por jobs já rodando). Uma chamada leve (page_size=1) por status
    # é suficiente para obter só o "count" sem baixar os jobs.
    queue_global = None
    try:
        pending = aap.get("/api/controller/v2/jobs/", {"status": "pending", "page_size": 1})
        waiting = aap.get("/api/controller/v2/jobs/", {"status": "waiting", "page_size": 1})
        queue_global = int(pending.get("count", 0)) + int(waiting.get("count", 0))
        print(f"[health] fila global (pending+waiting): {queue_global}")
    except requests.RequestException as exc:
        print(f"[health] fila: ERRO -> {exc}")

    health["queue_global"] = queue_global
    return health


def build_platform_health(raw_health):
    """Estrutura pequena e normalizada para o Grafana (item 12 das instruções).
    Controller = nó com node_type == 'hybrid'. Execution Nodes = node_type == 'execution'.
    """
    instances = (raw_health.get("instances") or {}).get("results", [])

    def normalize_node(node):
        return {
            "name": node.get("hostname"),
            "status": node.get("node_state"),
            "capacity": node.get("capacity"),
            "consumed_capacity": node.get("consumed_capacity"),
            "percent_capacity_remaining": node.get("percent_capacity_remaining"),
            "jobs_running": node.get("jobs_running"),
        }

    controller = None
    execution_nodes = []
    for node in instances:
        node_type = node.get("node_type")
        if node_type == "hybrid" and controller is None:
            controller = normalize_node(node)
        elif node_type == "execution":
            execution_nodes.append(normalize_node(node))

    # Saúde do cluster em % única: soma capacity e consumed_capacity de TODOS
    # os nós (controller + execution nodes) e calcula o % restante sobre o
    # total somado — não é a média simples dos percentuais de cada nó.
    # Isso pondera corretamente nós com capacidades diferentes (um nó de
    # capacidade 600 pesa o dobro de um nó de capacidade 300 no resultado
    # final, que é o comportamento correto para "saúde do cluster").
    all_nodes = ([controller] if controller else []) + execution_nodes
    total_capacity = sum(n["capacity"] for n in all_nodes if n.get("capacity") is not None)
    total_consumed = sum(n["consumed_capacity"] for n in all_nodes if n.get("consumed_capacity") is not None)
    cluster_capacity_health_pct = (
        round((total_capacity - total_consumed) / total_capacity * 100, 2)
        if total_capacity else None
    )

    return {
        "controller": controller,
        "execution_nodes": execution_nodes,
        "cluster_capacity_health_pct": cluster_capacity_health_pct,
        # Só existe em nível global no Controller — a API não expõe fila
        # por Execution Node específico (ver collect_controller_health).
        "queue_pending_global": raw_health.get("queue_global"),
    }


# --------------------------------------------------------------------------
# Histórico em disco
# --------------------------------------------------------------------------
def load_json_file(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_history(history_dir):
    jobs_path = os.path.join(history_dir, "jobs.json")
    hosts_path = os.path.join(history_dir, "job_host_summaries.json")

    jobs_raw = load_json_file(jobs_path, {"jobs": {}})
    hosts_raw = load_json_file(hosts_path, {"summaries": {}})

    jobs = jobs_raw.get("jobs", {})
    summaries = hosts_raw.get("summaries", {})
    return jobs, summaries


def save_history(history_dir, jobs, summaries):
    save_json(os.path.join(history_dir, "jobs.json"), {"jobs": jobs, "count": len(jobs)})
    save_json(os.path.join(history_dir, "job_host_summaries.json"),
              {"summaries": summaries, "count": len(summaries)})


def determine_collection_window(existing_jobs, max_history_days, overlap_days):
    """Decide a janela de coleta:
      - histórico vazio -> carga inicial de max_history_days dias;
      - histórico existente -> desde a data mais recente já coletada, menos
        um overlap de alguns dias (para pegar jobs que ficaram running/pending
        e jobs criados um pouco antes mas ainda não vistos).
    Nunca coleta (nem retém) além de max_history_days para trás.
    """
    end = today_str()
    floor_start = days_ago_str(max_history_days)

    if not existing_jobs:
        return floor_start, end, "carga_inicial"

    latest = None
    for job in existing_jobs.values():
        d = parse_date_only(job.get("started") or job.get("created"))
        if d and (latest is None or d > latest):
            latest = d

    if not latest:
        return floor_start, end, "carga_inicial"

    incremental_start = (datetime.fromisoformat(latest) - timedelta(days=overlap_days)).strftime("%Y-%m-%d")
    start = max(incremental_start, floor_start)
    return start, end, "incremental"


def merge_jobs_history(existing_jobs, new_compact_jobs):
    for job in new_compact_jobs:
        existing_jobs[str(job["job_id"])] = job
    return existing_jobs


def prune_jobs_history(jobs, max_history_days):
    cutoff = days_ago_str(max_history_days)
    kept = {
        jid: job for jid, job in jobs.items()
        if (parse_date_only(job.get("started") or job.get("created")) or "0000-00-00") >= cutoff
    }
    return kept


def merge_host_summaries_history(existing_summaries, new_summaries):
    for summary in new_summaries:
        existing_summaries[str(summary["job_id"])] = summary
    return existing_summaries


def prune_host_summaries(summaries, valid_job_ids):
    return {jid: s for jid, s in summaries.items() if jid in valid_job_ids}


def build_executions_view(jobs, summaries, only_terminal=True):
    """Junta cada job do histórico com seu job_host_summary (se existir).

    only_terminal=True (padrão): descarta jobs que não estão em um status
    terminal (successful/failed/error). O coletor roda 1x/dia buscando o
    dia anterior, então running/pending/waiting/new não deveriam aparecer
    de forma relevante nesse recorte — e não devem contaminar execuções,
    success_rate, duração média, hosts_impacted nem tendência. "canceled"
    também é descartado (não é sucesso nem falha de execução). Esses jobs
    continuam guardados no histórico em disco com seu status real; só não
    entram nos agregados enquanto não chegarem a um estado terminal.
    """
    executions = []
    for jid, job in jobs.items():
        if only_terminal and job.get("status") not in TERMINAL_STATUSES:
            continue
        execution = dict(job)
        summary = summaries.get(jid)
        execution["hosts"] = summary["hosts"] if summary else []
        execution["has_host_data"] = summary is not None
        executions.append(execution)
    return executions


# --------------------------------------------------------------------------
# Cálculo de métricas
# --------------------------------------------------------------------------
def filter_by_period(executions, period_key, max_history_days):
    days = PERIOD_DAYS[period_key]
    if days is None:
        days = max_history_days
    cutoff = days_ago_str(days)
    return [
        e for e in executions
        if (parse_date_only(e.get("started") or e.get("created")) or "0000-00-00") >= cutoff
    ]


def _template_key(execution):
    tid = execution.get("template_id")
    name = execution.get("template_name") or "desconhecido"
    return (tid, name)


def compute_templates(executions):
    """TODOS os templates (não só top 30). Um item por (template_id, name)."""
    stats = defaultdict(lambda: {
        "executions": 0, "success": 0, "failures": 0,
        "durations": [], "hosts": set(),
    })

    for e in executions:
        key = _template_key(e)
        stat = stats[key]
        stat["executions"] += 1
        if e["status"] == "successful":
            stat["success"] += 1
        if e["status"] in ("failed", "error"):
            stat["failures"] += 1
        stat["durations"].append(e.get("elapsed", 0.0))
        stat["hosts"].update(e.get("hosts", []))

    templates = []
    for (tid, name), stat in stats.items():
        total = stat["executions"]
        templates.append({
            "template_id": tid,
            "name": name,
            "executions": total,
            "failures": stat["failures"],
            "success_rate": round(stat["success"] / total * 100, 1) if total else 0.0,
            "avg_duration_seconds": round(mean(stat["durations"]), 1) if stat["durations"] else 0.0,
            "hosts_impacted": len(stat["hosts"]),
        })

    return templates


def _consolidated_name(name):
    return "Escondida* (consolidado)" if (name or "").lower().startswith("escondida") else name


def compute_top30(executions):
    """Top 30 por execuções, com consolidação de 'escondida*'. Recalculado
    diretamente das execuções (não a partir de compute_templates()), para que
    a união de hosts e a duração média do grupo consolidado sejam corretas.
    """
    stats = defaultdict(lambda: {
        "executions": 0, "success": 0, "failures": 0,
        "durations": [], "hosts": set(), "template_ids": set(),
    })

    for e in executions:
        name = _consolidated_name(e.get("template_name"))
        stat = stats[name]
        stat["executions"] += 1
        if e["status"] == "successful":
            stat["success"] += 1
        if e["status"] in ("failed", "error"):
            stat["failures"] += 1
        stat["durations"].append(e.get("elapsed", 0.0))
        stat["hosts"].update(e.get("hosts", []))
        if e.get("template_id") is not None:
            stat["template_ids"].add(e["template_id"])

    top = []
    for name, stat in stats.items():
        total = stat["executions"]
        tids = sorted(stat["template_ids"])
        top.append({
            # id único quando o grupo corresponde a 1 template só;
            # None quando é um grupo consolidado (ex.: Escondida*).
            "template_id": tids[0] if len(tids) == 1 else None,
            "name": name,
            "executions": total,
            "failures": stat["failures"],
            "success_rate": round(stat["success"] / total * 100, 1) if total else 0.0,
            "avg_duration_seconds": round(mean(stat["durations"]), 1) if stat["durations"] else 0.0,
            "hosts_impacted": len(stat["hosts"]),
        })

    top.sort(key=lambda x: x["executions"], reverse=True)
    return top[:30]


def compute_curation(templates):
    """TODOS os templates com success_rate < 90%. Só números — sem
    classificação de gravidade (isso fica para o Grafana)."""
    backlog = [t for t in templates if t["success_rate"] < 90]
    backlog.sort(key=lambda x: x["success_rate"])  # pior primeiro

    curation_map = [
        {
            "template_id": t["template_id"],
            "name": t["name"],
            "executions": t["executions"],
            "failures": t["failures"],
            "success_rate": t["success_rate"],
        }
        for t in backlog
    ]

    return {
        "backlog_count": len(backlog),
        "templates": backlog,
        "map": curation_map,
    }


def compute_summary(executions):
    total = len(executions)
    if not total:
        return {
            "executions": 0, "failures": 0, "success_rate": 0.0,
            "avg_duration_seconds": 0.0, "hosts_impacted": 0,
        }

    success = sum(1 for e in executions if e["status"] == "successful")
    failures = sum(1 for e in executions if e["status"] in ("failed", "error"))
    durations = [e.get("elapsed", 0.0) for e in executions]

    hosts = set()
    for e in executions:
        hosts.update(e.get("hosts", []))

    return {
        "executions": total,
        "failures": failures,
        "success_rate": round(success / total * 100, 1),
        "avg_duration_seconds": round(mean(durations), 1) if durations else 0.0,
        "hosts_impacted": len(hosts),
    }


def compute_trend(executions):
    by_day = defaultdict(lambda: {"executions": 0, "failures": 0})
    for e in executions:
        day = parse_date_only(e.get("started") or e.get("created"))
        if not day:
            continue
        by_day[day]["executions"] += 1
        if e["status"] in ("failed", "error"):
            by_day[day]["failures"] += 1

    return [{"date": day, **values} for day, values in sorted(by_day.items())]


def build_org_block(org_id, org_name, executions, max_history_days):
    periods = {}
    for period_key in PERIOD_DAYS:
        subset = filter_by_period(executions, period_key, max_history_days)
        templates = compute_templates(subset)
        periods[period_key] = {
            "summary": compute_summary(subset),
            "templates": templates,
            "top_30": compute_top30(subset),
            "curation": compute_curation(templates),
        }

    return {
        "id": org_id,
        "name": org_name,
        "periods": periods,
        "trend": compute_trend(executions),  # série completa; Grafana filtra por data
    }


def compute_host_data_diagnostics(executions):
    """Cobertura de hosts calculada só sobre execuções tipo 'job' (as únicas
    que legitimamente têm job_host_summaries). Evita confundir 'sem dado'
    com 'não se aplica' (project_update/inventory_update/workflow_job/system_job)."""
    eligible = [e for e in executions if e.get("job_type") in JOB_TYPES_WITH_HOSTS]
    with_data = [e for e in eligible if e.get("has_host_data")]
    total_eligible = len(eligible)
    coverage = round(len(with_data) / total_eligible * 100, 1) if total_eligible else 0.0
    return {
        "eligible_job_type_executions": total_eligible,
        "eligible_with_host_data": len(with_data),
        "host_data_coverage_pct": coverage,
    }


def main():
    args = parse_args()

    if not args.token:
        for required in ("url", "username", "password"):
            if not getattr(args, required):
                sys.exit(f"Faltou --{required} (ou AAP_{required.upper()}), ou informe --token.")
    elif not args.url:
        sys.exit("Faltou --url (ou AAP_URL).")

    os.makedirs(args.output_dir, exist_ok=True)

    print("=" * 70)
    print("AAP CONTROLLER - COLETA E MÉTRICAS (histórico + multi-org)")
    print("=" * 70)

    aap = AAP(args.url, args.username, args.password, args.token, args.proxy, args.insecure)

    manual_single_org = bool(args.org) or args.no_history

    if manual_single_org:
        # Modo pontual: comportamento antigo, sem tocar no histórico.
        org_id, org_name = resolve_organization(aap, args.org)
        days = PERIOD_DAYS[args.period]
        start = days_ago_str(days) if days is not None else None
        end = today_str()

        print(f"[modo] consulta pontual | org={org_name or 'todas'} | período={args.period}")

        raw_jobs = collect_jobs(aap, start, end, args.page_size, org_id)
        compacted = [compact_job(j) for j in raw_jobs]

        host_summaries = []
        if not args.skip_host_summaries:
            eligible = [e for e in compacted if e["job_type"] in JOB_TYPES_WITH_HOSTS]
            targets = eligible if not args.max_host_summary_jobs else eligible[: args.max_host_summary_jobs]
            print(f"[hosts] coletando job_host_summaries de {len(targets)} jobs elegíveis")
            for i, e in enumerate(targets, 1):
                try:
                    host_summaries.append(collect_host_summary(aap, e["job_id"], args.host_page_size))
                    print(f"[hosts] {i}/{len(targets)} job={e['job_id']}")
                except requests.RequestException as exc:
                    print(f"[hosts] job={e['job_id']}: ERRO -> {exc}")

        summaries_by_id = {str(s["job_id"]): s for s in host_summaries}
        jobs_by_id = {str(j["job_id"]): j for j in compacted}
        executions = build_executions_view(jobs_by_id, summaries_by_id)

        raw_health = collect_controller_health(aap)
        org_block = build_org_block(org_id, org_name or "todas", executions, args.max_history_days)
        diagnostics = compute_host_data_diagnostics(executions)

        dashboard_data = {
            "meta": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "mode": "consulta_pontual",
                "window": {"start": start, "end": end},
                "diagnostics": diagnostics,
            },
            "organizations": {(str(org_id) if org_id else "ALL"): org_block},
            "platform_health": build_platform_health(raw_health),
        }
        save_json(os.path.join(args.output_dir, "dashboard_data.json"), dashboard_data)
        print(f"\nArquivo em: {args.output_dir}/dashboard_data.json")
        return

    # ---------------- Modo produção: histórico multi-org ----------------
    jobs_history, summaries_history = load_history(args.history_dir)
    start, end, collection_mode = determine_collection_window(
        jobs_history, args.max_history_days, args.overlap_days
    )
    print(f"[histórico] modo={collection_mode} | janela de coleta={start}..{end} | "
          f"jobs já no histórico={len(jobs_history)}")

    raw_jobs = collect_jobs(aap, start, end, args.page_size, org_id=None)
    new_compacted = [compact_job(j) for j in raw_jobs]

    jobs_history = merge_jobs_history(jobs_history, new_compacted)
    jobs_history = prune_jobs_history(jobs_history, args.max_history_days)

    # Só busca job_host_summaries para jobs novos/atualizados desta rodada,
    # do tipo elegível — não varre os 730 dias inteiros todo dia.
    host_summaries = []
    if not args.skip_host_summaries:
        eligible = [e for e in new_compacted if e["job_type"] in JOB_TYPES_WITH_HOSTS]
        targets = eligible if not args.max_host_summary_jobs else eligible[: args.max_host_summary_jobs]
        print(f"[hosts] coletando job_host_summaries de {len(targets)} jobs elegíveis (novos/atualizados)")
        for i, e in enumerate(targets, 1):
            try:
                summary = collect_host_summary(aap, e["job_id"], args.host_page_size)
                host_summaries.append(summary)
                print(f"[hosts] {i}/{len(targets)} job={e['job_id']} hosts={summary['host_count']}")
            except requests.RequestException as exc:
                print(f"[hosts] job={e['job_id']}: ERRO -> {exc}")

    summaries_history = merge_host_summaries_history(summaries_history, host_summaries)
    summaries_history = prune_host_summaries(summaries_history, set(jobs_history.keys()))

    save_history(args.history_dir, jobs_history, summaries_history)

    executions = build_executions_view(jobs_history, summaries_history)

    # Agrupa por organização + ALL
    by_org = defaultdict(list)
    for e in executions:
        by_org[(e.get("org_id"), e.get("org_name"))].append(e)

    organizations = {"ALL": build_org_block(None, "ALL", executions, args.max_history_days)}
    for (org_id, org_name), org_executions in by_org.items():
        key = str(org_id) if org_id is not None else "sem_organizacao"
        organizations[key] = build_org_block(org_id, org_name, org_executions, args.max_history_days)

    raw_health = collect_controller_health(aap)
    diagnostics = compute_host_data_diagnostics(executions)

    history_dates = [
        parse_date_only(j.get("started") or j.get("created")) for j in jobs_history.values()
    ]
    history_dates = [d for d in history_dates if d]

    dashboard_data = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": collection_mode,
            "history_start": min(history_dates) if history_dates else None,
            "history_end": max(history_dates) if history_dates else None,
            "max_history_days": args.max_history_days,
            "periods": list(PERIOD_DAYS.keys()),
            "diagnostics": diagnostics,
        },
        "organizations": organizations,
        "platform_health": build_platform_health(raw_health),
    }

    save_json(os.path.join(args.output_dir, "dashboard_data.json"), dashboard_data)

    print("\n" + "=" * 70)
    print("RESULTADO")
    print("=" * 70)
    print(f"Modo de coleta........: {collection_mode}")
    print(f"Jobs no histórico.....: {len(jobs_history)}")
    print(f"Organizações..........: {len(organizations) - 1} + ALL")
    print(f"Cobertura hosts (tipo job elegível): {diagnostics['host_data_coverage_pct']}%")
    all_summary_all_period = organizations["ALL"]["periods"]["all"]["summary"]
    print(f"ALL / all-time: execuções={all_summary_all_period['executions']} "
          f"| falhas={all_summary_all_period['failures']} "
          f"| sucesso={all_summary_all_period['success_rate']}%")
    print(f"\nArquivo em: {args.output_dir}/dashboard_data.json")
    print(f"Histórico em: {args.history_dir}/jobs.json, {args.history_dir}/job_host_summaries.json")


if __name__ == "__main__":
    main()