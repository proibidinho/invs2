#!/usr/bin/env python3
"""
collect_metrics.py — Coletor + calculadora de métricas AAP Controller.

Evolução do collect.py original:
  - Continua usando SOMENTE a API do Controller (tokens/jobs/instances/ping/dashboard),
    igual ao collect.py. Não usa analytics/job_explorer/roi_templates.
  - Adiciona filtro de --org (organização) e --period (período pré-definido).
  - Corrige o bug do collect.py original (variável "top_10" inexistente).
  - Gera, além dos dados brutos, os artefatos já prontos para o dashboard:
      * quick_metrics.json      -> execuções, sucesso, falhas, duração média,
                                    hosts impactados, autonomia, top_30
      * curation_backlog.json   -> item 1 das instruções: templates do top_30
                                    com < 80% de sucesso (nome, % falhas, qtd falhas)
      * curation_map.json       -> item 2 das instruções: TODOS os templates do
                                    top_30, para o mapa em cruz (volume x falha x impacto)
      * platform_health.json    -> item 3 das instruções: instances/ping/dashboard
      * failure_causes.json     -> principais causas de falha via /stdout/ (BETA,
                                    heurístico — ainda sem exemplo de saída real)

Fontes de API usadas (Controller, ver catálogo em developers.redhat.com):
  - POST /api/controller/v2/tokens/
  - GET  /api/controller/v2/organizations/
  - GET  /api/controller/v2/jobs/
  - GET  /api/controller/v2/jobs/{id}/job_host_summaries/
  - GET  /api/controller/v2/jobs/{id}/stdout/?format=json   (causas de falha, beta)
  - GET  /api/controller/v2/instances/
  - GET  /api/controller/v2/ping/
  - GET  /api/controller/v2/dashboard/

Uso típico:
  python collect_metrics.py --period 30d
  python collect_metrics.py --period 90d --org org-clbt-ti-ops-seginfo
  python collect_metrics.py --start-date 2026-01-01 --end-date 2026-08-27
  python collect_metrics.py --period all --org 12 --collect-failure-causes
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean, median

from dotenv import load_dotenv

load_dotenv()

try:
    import requests
except ImportError:
    sys.exit("Falta a lib requests. Rode: pip install requests")

import urllib3


# --------------------------------------------------------------------------
# Períodos pré-definidos (item 4 das instruções: só produção, então os únicos
# filtros que devem existir são tempo / organização / período).
# --------------------------------------------------------------------------
PERIOD_DAYS = {
    "7d": 7,
    "14d": 14,
    "30d": 30,
    "3m": 90,
    "6m": 180,
    "1y": 365,
    "all": None,  # desde o início
}


def parse_args():
    p = argparse.ArgumentParser(
        description="Coleta e calcula métricas operacionais do AAP Controller"
    )

    # Conexão
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

    # Filtros (únicos que devem existir, conforme instruções: tempo / org / período)
    p.add_argument(
        "--period",
        choices=list(PERIOD_DAYS.keys()),
        default=os.environ.get("AAP_PERIOD", "7d"),
        help="Período pré-definido: 7d, 14d, 30d, 3m, 6m, 1y, all (desde o início).",
    )
    p.add_argument("--days", type=int, default=None,
                    help="Compatibilidade com o script antigo. Se informado, tem prioridade sobre --period.")
    p.add_argument("--start-date", default=os.environ.get("AAP_START_DATE", ""))
    p.add_argument("--end-date", default=os.environ.get("AAP_END_DATE", ""))
    p.add_argument(
        "--org",
        default=os.environ.get("AAP_ORG", ""),
        help="Nome ou ID da organização. Vazio = todas as organizações.",
    )

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
        help="Limita quantos jobs recebem consulta de job_host_summaries. 0 = todos.",
    )

    # Causas de falha (beta — depende de /stdout/, ainda sem exemplo de saída real)
    p.add_argument(
        "--collect-failure-causes",
        action="store_true",
        default=os.environ.get("AAP_COLLECT_FAILURE_CAUSES", "false").lower() == "true",
        help="Ativa a consulta (beta) de /stdout/ dos jobs falhos para tentar "
             "identificar as causas mais comuns de falha.",
    )
    p.add_argument(
        "--max-failure-causes-jobs",
        type=int,
        default=int(os.environ.get("AAP_MAX_FAILURE_CAUSES_JOBS", "50")),
        help="Quantos jobs falhos (no máximo) terão o stdout analisado. 0 = todos.",
    )

    p.add_argument("--output-dir", default=os.environ.get("AAP_OUTPUT_DIR", "./saida"))

    return p.parse_args()


def date_window(args):
    """Resolve a janela de datas a partir de --start-date/--end-date, --days ou --period."""
    end = args.end_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if args.start_date:
        return args.start_date, end

    days = args.days if args.days is not None else PERIOD_DAYS[args.period]

    if days is None:
        # "all" / desde o início: não define created__gte
        return None, end

    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    return start, end


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


def collect_jobs(aap, start, end, page_size, org_id):
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
    project = sf.get("project") or {}
    inventory = sf.get("inventory") or {}

    started = job.get("started") or job.get("created")

    queue_seconds = 0.0
    if job.get("created") and started:
        try:
            created_dt = datetime.fromisoformat(job["created"].replace("Z", "+00:00"))
            started_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
            queue_seconds = max(0.0, (started_dt - created_dt).total_seconds())
        except ValueError:
            pass

    return {
        "job_id": job.get("id"),
        "template_id": template.get("id") or job.get("job_template"),
        "template_name": template.get("name") or job.get("name"),
        "status": job.get("status", "unknown"),
        "failed": bool(job.get("failed", job.get("status") in ("failed", "error"))),
        "created": job.get("created"),
        "started": started,
        "finished": job.get("finished"),
        "elapsed": float(job.get("elapsed") or 0),
        "queue_seconds": round(queue_seconds, 3),
        "org_id": job.get("organization") or organization.get("id"),
        "org_name": organization.get("name"),
        "project_name": project.get("name"),
        "inventory_name": inventory.get("name"),
        "launch_type": job.get("launch_type", "manual"),
        "execution_node": job.get("execution_node"),
        "controller_node": job.get("controller_node"),
    }


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

    hosts = []
    failed_hosts = 0
    for row in rows:
        host_name = row.get("host_name")
        if host_name:
            hosts.append(host_name)
        if row.get("failed") is True:
            failed_hosts += 1

    return {
        "job_id": job_id,
        "host_count": total,
        "failed_host_count": failed_hosts,
        "hosts": sorted(set(hosts)),
    }


def collect_controller_health(aap):
    """Item 3 das instruções: saúde da plataforma = instances + ping + dashboard."""
    health = {}
    for name, path in (
        ("instances", "/api/controller/v2/instances/"),
        ("ping", "/api/controller/v2/ping/"),
        ("dashboard", "/api/controller/v2/dashboard/"),
    ):
        try:
            health[name] = aap.get(path, {"page": 1, "page_size": 200})
            print(f"[health] {name}: OK")
        except requests.RequestException as exc:
            print(f"[health] {name}: ERRO -> {exc}")
            health[name] = {"error": str(exc)}
    return health


def merge_host_summaries(executions, summaries):
    by_job = {item["job_id"]: item for item in summaries}
    for execution in executions:
        hs = by_job.get(execution["job_id"])
        if hs:
            execution["host_count"] = hs["host_count"]
            execution["failed_host_count"] = hs["failed_host_count"]
            execution["hosts"] = hs["hosts"]
        else:
            execution["host_count"] = 0
            execution["failed_host_count"] = 0
            execution["hosts"] = []
    return executions


def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def quick_metrics(executions, host_data_jobs_considered):
    """Item: execuções, sucesso, falhas, duração média, hosts impactados, autonomia, top_30."""
    if not executions:
        return {
            "executions": 0, "failures": 0, "success_rate": 0.0,
            "avg_duration_seconds": 0.0, "hosts_impacted": 0, "failed_hosts": 0,
            "autonomy": 0.0, "top_30": [], "trend": [], "host_data_coverage": 0.0,
        }

    total = len(executions)
    failures = sum(1 for e in executions if e["status"] in ("failed", "error"))
    success_rate = sum(1 for e in executions if e["status"] == "successful") / total * 100

    durations = [e["elapsed"] for e in executions]
    avg_duration = mean(durations) if durations else 0

    hosts = set()
    for e in executions:
        hosts.update(e.get("hosts", []))

    failed_hosts = sum(e.get("failed_host_count", 0) for e in executions)

    automatic = sum(1 for e in executions if e.get("launch_type") in ("scheduled", "workflow"))

    # name -> {executions, success, failures, host_count, failed_host_count}
    template_stats = defaultdict(lambda: {
        "executions": 0, "success": 0, "failures": 0,
        "host_count": 0, "failed_host_count": 0,
    })
    for e in executions:
        name = e.get("template_name") or "desconhecido"
        if name.lower().startswith("escondida"):
            name = "Escondida* (consolidado)"

        stat = template_stats[name]
        stat["executions"] += 1
        if e["status"] == "successful":
            stat["success"] += 1
        if e["status"] in ("failed", "error"):
            stat["failures"] += 1
        stat["host_count"] += e.get("host_count", 0)
        stat["failed_host_count"] += e.get("failed_host_count", 0)

    top_30 = []
    for name, stat in template_stats.items():
        top_30.append({
            "name": name,
            "executions": stat["executions"],
            "success_rate": round(stat["success"] / stat["executions"] * 100, 1),
            "failures": stat["failures"],
            "host_count": stat["host_count"],
            "failed_host_count": stat["failed_host_count"],
        })

    top_30.sort(key=lambda x: x["executions"], reverse=True)
    top_30 = top_30[:30]

    by_day = defaultdict(lambda: {"executions": 0, "failures": 0})
    for e in executions:
        dt = parse_dt(e.get("started"))
        if not dt:
            continue
        key = dt.date().isoformat()
        by_day[key]["executions"] += 1
        if e["status"] in ("failed", "error"):
            by_day[key]["failures"] += 1

    trend = [{"date": day, **values} for day, values in sorted(by_day.items())]

    return {
        "executions": total,
        "failures": failures,
        "success_rate": round(success_rate, 1),
        "avg_duration_seconds": round(avg_duration, 1),
        "hosts_impacted": len(hosts),
        "failed_hosts": failed_hosts,
        "autonomy": round(automatic / total * 100, 1),
        "top_30": top_30,
        "trend": trend,
        # dado de hosts só é confiável para os jobs que tiveram job_host_summaries coletado
        "host_data_coverage": round(host_data_jobs_considered / total * 100, 1) if total else 0.0,
    }


def curation_backlog(top_30):
    """
    Instrução 1: backlog de curadoria contém, dos templates do top_30 com
    menos de 80% de sucesso: nome, % de falhas e quantidade de falhas.
    """
    backlog = [
        {
            "name": item["name"],
            "failure_rate": round(100 - item["success_rate"], 1),
            "failures": item["failures"],
        }
        for item in top_30
        if item["success_rate"] < 80
    ]
    backlog.sort(key=lambda x: x["failures"], reverse=True)
    return backlog


def curation_map(top_30):
    """
    Instrução 2: mapa de curadoria usa os mesmos dados, mas de TODOS os
    templates do top_30, para montar o gráfico em cruz de prioridade
    (volume x falha x impacto).
    """
    if not top_30:
        return []

    volumes = [i["executions"] for i in top_30]
    failure_rates = [round(100 - i["success_rate"], 1) for i in top_30]

    vol_median = median(volumes)
    fail_median = median(failure_rates)

    points = []
    for item, fail_rate in zip(top_30, failure_rates):
        # impacto: prioriza hosts falhos reais; se não houver dado de host
        # (job_host_summaries não coletado para esses jobs), usa a quantidade
        # de execuções falhas como proxy de impacto.
        impact = item["failed_host_count"] if item["host_count"] > 0 else item["failures"]

        high_volume = item["executions"] >= vol_median
        high_failure = fail_rate >= fail_median

        if high_volume and high_failure:
            quadrant = "critico"          # alto volume, alta falha
        elif high_volume and not high_failure:
            quadrant = "monitorar"        # alto volume, baixa falha
        elif not high_volume and high_failure:
            quadrant = "risco_pontual"    # baixo volume, alta falha
        else:
            quadrant = "estavel"          # baixo volume, baixa falha

        points.append({
            "name": item["name"],
            "volume": item["executions"],
            "failure_rate": fail_rate,
            "impact": impact,
            "quadrant": quadrant,
        })

    return points


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
WHITESPACE_RE = re.compile(r"\s+")


def _simplify_reason(line):
    line = ANSI_RE.sub("", line).strip()
    line = WHITESPACE_RE.sub(" ", line)
    return line[:180]


def collect_failure_causes(aap, executions, max_jobs, page_size_unused=None):
    """
    BETA / heurístico: tenta identificar as principais causas de falha via
    GET /api/controller/v2/jobs/{id}/stdout/?format=json dos jobs falhos.

    Ainda não validado com um exemplo real de saída do /stdout/ (conforme
    combinado, o usuário ainda não coletou essa amostra). Ajustar a função
    _simplify_reason() / os marcadores de busca ("FAILED! =>", "fatal:",
    "UNREACHABLE! =>") assim que houver uma amostra real para calibrar.
    """
    failed = [e for e in executions if e["status"] in ("failed", "error")]
    if max_jobs and max_jobs > 0:
        failed = failed[:max_jobs]

    causes = Counter()
    errors = 0

    for execution in failed:
        job_id = execution["job_id"]
        try:
            data = aap.get(f"/api/controller/v2/jobs/{job_id}/stdout/", {"format": "json"})
        except requests.RequestException as exc:
            errors += 1
            print(f"[causas] job={job_id}: ERRO -> {exc}")
            continue

        stdout_text = data.get("content", "") if isinstance(data, dict) else str(data)

        reason = None
        for line in stdout_text.splitlines():
            if "FAILED! =>" in line or "UNREACHABLE! =>" in line or line.strip().startswith("fatal:"):
                reason = _simplify_reason(line)
                break

        causes[reason or "motivo não identificado (revisar stdout manualmente)"] += 1

    ranked = [{"reason": reason, "count": count} for reason, count in causes.most_common()]

    return {
        "results": ranked,
        "jobs_analyzed": len(failed) - errors,
        "jobs_with_error": errors,
        "note": (
            "BETA: extração heurística baseada em linhas 'FAILED! =>' / 'fatal:' / "
            "'UNREACHABLE! =>' do stdout. Ainda sem amostra real de /stdout/ para "
            "validar o parser — revisar antes de usar em produção."
        ),
    }


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    args = parse_args()

    if not args.token:
        for required in ("url", "username", "password"):
            if not getattr(args, required):
                sys.exit(f"Faltou --{required} (ou AAP_{required.upper()}), ou informe --token.")
    elif not args.url:
        sys.exit("Faltou --url (ou AAP_URL).")

    os.makedirs(args.output_dir, exist_ok=True)

    start, end = date_window(args)

    print("=" * 70)
    print("AAP CONTROLLER - COLETA E MÉTRICAS")
    print("=" * 70)

    aap = AAP(args.url, args.username, args.password, args.token, args.proxy, args.insecure)

    org_id, org_name = resolve_organization(aap, args.org)
    if org_id:
        print(f"[org] filtrando por organização: {org_name} (id={org_id})")

    raw_jobs = collect_jobs(aap, start, end, args.page_size, org_id)
    executions = [compact_job(job) for job in raw_jobs]

    host_summaries = []
    if not args.skip_host_summaries:
        jobs_for_hosts = executions
        if args.max_host_summary_jobs > 0:
            jobs_for_hosts = executions[: args.max_host_summary_jobs]

        print(f"[hosts] coletando job_host_summaries de {len(jobs_for_hosts)} jobs")

        for index, execution in enumerate(jobs_for_hosts, start=1):
            job_id = execution["job_id"]
            try:
                summary = collect_host_summary(aap, job_id, args.host_page_size)
                host_summaries.append(summary)
                print(f"[hosts] {index}/{len(jobs_for_hosts)} job={job_id} "
                      f"hosts={summary['host_count']} falhos={summary['failed_host_count']}")
            except requests.RequestException as exc:
                print(f"[hosts] job={job_id}: ERRO -> {exc}")

    executions = merge_host_summaries(executions, host_summaries)

    health = collect_controller_health(aap)
    metrics = quick_metrics(executions, host_data_jobs_considered=len(host_summaries))
    backlog = curation_backlog(metrics["top_30"])
    curation_map_data = curation_map(metrics["top_30"])

    causes = {"results": [], "note": "Coleta de causas de falha desativada (--collect-failure-causes)."}
    if args.collect_failure_causes:
        print("[causas] coletando stdout dos jobs falhos (beta)...")
        causes = collect_failure_causes(aap, executions, args.max_failure_causes_jobs)

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"start": start, "end": end},
        "organization": {"id": org_id, "name": org_name} if org_id else None,
        "period": args.period,
    }

    save_json(os.path.join(args.output_dir, "jobs.json"), {"results": executions, "count": len(executions)})
    save_json(os.path.join(args.output_dir, "job_host_summaries.json"),
              {"results": host_summaries, "count": len(host_summaries)})
    save_json(os.path.join(args.output_dir, "platform_health.json"), health)
    save_json(os.path.join(args.output_dir, "quick_metrics.json"), {**meta, **metrics})
    save_json(os.path.join(args.output_dir, "curation_backlog.json"), {**meta, "results": backlog})
    save_json(os.path.join(args.output_dir, "curation_map.json"), {**meta, "results": curation_map_data})
    save_json(os.path.join(args.output_dir, "failure_causes.json"), {**meta, **causes})

    print("\n" + "=" * 70)
    print("RESULTADO RÁPIDO")
    print("=" * 70)
    print(f"Organização...........: {org_name or 'todas'}")
    print(f"Período...............: {args.period} ({start or 'início'} .. {end})")
    print(f"Execuções.............: {metrics['executions']}")
    print(f"Falhas................: {metrics['failures']}")
    print(f"Taxa de sucesso.......: {metrics['success_rate']}%")
    print(f"Duração média.........: {metrics['avg_duration_seconds']} s")
    print(f"Hosts impactados......: {metrics['hosts_impacted']}")
    print(f"Hosts com falha.......: {metrics['failed_hosts']}")
    print(f"Autonomia (proxy).....: {metrics['autonomy']}%")
    print(f"Cobertura dado hosts..: {metrics['host_data_coverage']}%")
    print(f"Backlog de curadoria..: {len(backlog)} template(s) < 80% sucesso")

    print("\nTop 30 (top 10 exibidos):")
    for item in metrics["top_30"][:10]:
        print(f"  - {item['name']}: {item['executions']} execuções | {item['success_rate']}% sucesso")

    print("\nArquivos em:", args.output_dir)
    for fname in (
        "jobs.json", "job_host_summaries.json", "platform_health.json",
        "quick_metrics.json", "curation_backlog.json", "curation_map.json",
        "failure_causes.json",
    ):
        print(f"  {args.output_dir}/{fname}")


if __name__ == "__main__":
    main()