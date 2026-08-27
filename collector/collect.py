#!/usr/bin/env python3
"""
Coletor AAP -> Controller.

Fontes usadas nesta etapa:
  - POST /api/controller/v2/tokens/
  - GET  /api/controller/v2/jobs/
  - GET  /api/controller/v2/jobs/{job_id}/job_host_summaries/
  - GET  /api/controller/v2/instances/
  - GET  /api/controller/v2/ping/
  - GET  /api/controller/v2/dashboard/

Não usa:
  - analytics/job_explorer
  - analytics/event_explorer
  - analytics/roi_templates
  - job_events
  - stdout

A ideia é coletar dados brutos/compactos e deixar cálculos mais elaborados
para a camada de métricas/backend.
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean, pstdev
from dotenv import load_dotenv

load_dotenv()
try:
    import requests
except ImportError:
    sys.exit(
        "Falta a lib requests. Rode pip install requests"
    )
import urllib3


def parse_args():
    p = argparse.ArgumentParser(description="Coleta operacional do AAP Controller")

    p.add_argument("--url", default=os.environ.get("AAP_URL", ""))
    p.add_argument("--username", default=os.environ.get("AAP_USERNAME", ""))
    p.add_argument("--password", default=os.environ.get("AAP_PASSWORD", ""))
    p.add_argument("--proxy", default=os.environ.get("AAP_PROXY", ""))
    p.add_argument(
        "--insecure",
        action="store_true",
        default=os.environ.get("AAP_INSECURE", "true").lower() == "true",
    )

    p.add_argument("--days", type=int, default=int(os.environ.get("AAP_DAYS", "7")))
    p.add_argument("--start-date", default=os.environ.get("AAP_START_DATE", ""))
    p.add_argument("--end-date", default=os.environ.get("AAP_END_DATE", ""))
    p.add_argument("--page-size", type=int, default=200)

    p.add_argument(
        "--output-dir",
        default=os.environ.get("AAP_OUTPUT_DIR", "./saida"),
    )

    p.add_argument(
        "--skip-host-summaries",
        action="store_true",
        help="Não consulta job_host_summaries; útil para testar rapidamente a API /jobs/.",
    )
    p.add_argument(
        "--max-host-summary-jobs",
        type=int,
        default=0,
        help="Limita a quantidade de jobs que terão job_host_summaries. 0 = todos.",
    )
    p.add_argument(
        "--host-page-size",
        type=int,
        default=200,
        help="Page size do endpoint job_host_summaries.",
    )

    return p.parse_args()


def date_window(args):
    end = args.end_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if args.start_date:
        start = args.start_date
    else:
        start = (
            datetime.now(timezone.utc) - timedelta(days=args.days)
        ).strftime("%Y-%m-%d")
    return start, end


class AAP:
    def __init__(self, url, username, password, proxy, insecure):
        self.url = url.rstrip("/")
        self.verify = not insecure
        self.session = requests.Session()

        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})

        if insecure:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        self.token = self._get_token(username, password)
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
            }
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
            raise RuntimeError(
                f"Token não retornado. HTTP {r.status_code}: {r.text[:300]}"
            )

        print("[auth] token obtido com sucesso")
        return token

    def get(self, path, params=None):
        r = self.session.get(
            f"{self.url}{path}",
            params=params,
            verify=self.verify,
            timeout=120,
        )
        r.raise_for_status()
        return r.json()


def collect_jobs(aap, start, end, page_size):
    date_filter = {
        "created__gte": f"{start}T00:00:00Z",
        "created__lte": f"{end}T23:59:59Z",
        "order_by": "started",
    }

    probe = aap.get(
        "/api/controller/v2/jobs/",
        {**date_filter, "page": 1, "page_size": 1},
    )

    count = int(probe.get("count", 0))
    pages = (count + page_size - 1) // page_size if count else 0

    print(
        f"[jobs] janela={start}..{end} | count={count} | "
        f"páginas={pages} | page_size={page_size}"
    )

    results = []

    for page in range(1, pages + 1):
        data = aap.get(
            "/api/controller/v2/jobs/",
            {**date_filter, "page": page, "page_size": page_size},
        )

        batch = data.get("results", [])
        results.extend(batch)

        print(
            f"[jobs] página {page}/{pages} -> +{len(batch)} "
            f"(total={len(results)})"
        )

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
            created_dt = datetime.fromisoformat(
                job["created"].replace("Z", "+00:00")
            )
            started_dt = datetime.fromisoformat(
                started.replace("Z", "+00:00")
            )
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
        "org_name": organization.get("name"),
        "project_name": project.get("name"),
        "inventory_name": inventory.get("name"),
        "launch_type": job.get("launch_type", "manual"),
        "execution_node": job.get("execution_node"),
        "controller_node": job.get("controller_node"),
    }


def collect_host_summary(aap, job_id, page_size):
    """
    Retorna somente o que interessa ao dashboard.

    Não armazena:
      processed, skipped, ignored, rescued
    """
    first = aap.get(
        f"/api/controller/v2/jobs/{job_id}/job_host_summaries/",
        {"page": 1, "page_size": page_size},
    )

    total = int(first.get("count", 0))
    pages = (total + page_size - 1) // page_size if total else 0

    rows = list(first.get("results", []))

    for page in range(2, pages + 1):
        data = aap.get(
            f"/api/controller/v2/jobs/{job_id}/job_host_summaries/",
            {"page": page, "page_size": page_size},
        )
        rows.extend(data.get("results", []))

    hosts = []
    failed_hosts = 0

    for row in rows:
        host_name = row.get("host_name")
        if host_name:
            hosts.append(host_name)

        if row.get("failed") is True:
            failed_hosts += 1

    # O count representa a quantidade de job_host_summary.
    # Como cada resultado representa um host do job, ele é a fonte do host_count.
    return {
        "job_id": job_id,
        "host_count": total,
        "failed_host_count": failed_hosts,
        "hosts": sorted(set(hosts)),
    }


def collect_controller_health(aap):
    """
    Saúde da plataforma:
      /instances/ -> estado/capacidade dos nós
      /ping/      -> heartbeat/estado geral
      /dashboard/ -> contadores agregados, incluindo credenciais
    """
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


def quick_metrics(executions):
    if not executions:
        return {
            "executions": 0,
            "failures": 0,
            "success_rate": 0.0,
            "avg_duration_seconds": 0.0,
            "hosts_impacted": 0,
            "failed_hosts": 0,
            "autonomy": 0.0,
            "top_30": [],
            "trend": [],
        }

    total = len(executions)
    failures = sum(1 for e in executions if e["status"] in ("failed", "error"))
    success_rate = sum(
        1 for e in executions if e["status"] == "successful"
    ) / total * 100

    durations = [e["elapsed"] for e in executions]
    avg_duration = mean(durations) if durations else 0

    hosts = set()
    for e in executions:
        hosts.update(e.get("hosts", []))

    failed_hosts = sum(e.get("failed_host_count", 0) for e in executions)

    automatic = sum(
        1
        for e in executions
        if e.get("launch_type") in ("scheduled", "workflow")
    )

    template_stats = defaultdict(lambda: {"executions": 0, "success": 0})
    for e in executions:
        name = e.get("template_name") or "desconhecido"
        # Mantém a mesma consolidação existente no projeto.
        if name.lower().startswith("escondida"):
            name = "Escondida* (consolidado)"

        template_stats[name]["executions"] += 1
        if e["status"] == "successful":
            template_stats[name]["success"] += 1

    top_30 = []
    for name, stat in template_stats.items():
        top_30.append(
            {
                "name": name,
                "executions": stat["executions"],
                "success_rate": round(
                    stat["success"] / stat["executions"] * 100, 1
                ),
            }
        )

    top_30.sort(key=lambda x: x["executions"], reverse=True)

    by_day = defaultdict(lambda: {"executions": 0, "failures": 0})
    for e in executions:
        dt = parse_dt(e.get("started"))
        if not dt:
            continue
        key = dt.date().isoformat()
        by_day[key]["executions"] += 1
        if e["status"] in ("failed", "error"):
            by_day[key]["failures"] += 1

    trend = [
        {"date": day, **values}
        for day, values in sorted(by_day.items())
    ]

    return {
        "executions": total,
        "failures": failures,
        "success_rate": round(success_rate, 1),
        "avg_duration_seconds": round(avg_duration, 1),
        "hosts_impacted": len(hosts),
        "failed_hosts": failed_hosts,
        "autonomy": round(automatic / total * 100, 1),
        "top_30": top_10[:30],
        "trend": trend,
    }


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    args = parse_args()

    for required in ("url", "username", "password"):
        if not getattr(args, required):
            sys.exit(
                f"Faltou --{required} "
                f"(ou AAP_{required.upper()})."
            )

    os.makedirs(args.output_dir, exist_ok=True)

    start, end = date_window(args)

    print("=" * 70)
    print("AAP CONTROLLER - COLETA OPERACIONAL")
    print("=" * 70)

    aap = AAP(
        args.url,
        args.username,
        args.password,
        args.proxy,
        args.insecure,
    )

    raw_jobs = collect_jobs(
        aap,
        start,
        end,
        args.page_size,
    )

    executions = [compact_job(job) for job in raw_jobs]

    host_summaries = []

    if not args.skip_host_summaries:
        jobs_for_hosts = executions
        if args.max_host_summary_jobs > 0:
            jobs_for_hosts = executions[: args.max_host_summary_jobs]

        print(
            f"[hosts] coletando job_host_summaries de "
            f"{len(jobs_for_hosts)} jobs"
        )

        for index, execution in enumerate(jobs_for_hosts, start=1):
            job_id = execution["job_id"]

            try:
                summary = collect_host_summary(
                    aap,
                    job_id,
                    args.host_page_size,
                )
                host_summaries.append(summary)

                print(
                    f"[hosts] {index}/{len(jobs_for_hosts)} "
                    f"job={job_id} "
                    f"hosts={summary['host_count']} "
                    f"falhos={summary['failed_host_count']}"
                )
            except requests.RequestException as exc:
                print(f"[hosts] job={job_id}: ERRO -> {exc}")

    executions = merge_host_summaries(
        executions,
        host_summaries,
    )

    health = collect_controller_health(aap)

    metrics = quick_metrics(executions)

    save_json(
        os.path.join(args.output_dir, "jobs.json"),
        {"results": executions, "count": len(executions)},
    )

    save_json(
        os.path.join(args.output_dir, "job_host_summaries.json"),
        {"results": host_summaries, "count": len(host_summaries)},
    )

    save_json(
        os.path.join(args.output_dir, "platform_health.json"),
        health,
    )

    save_json(
        os.path.join(args.output_dir, "quick_metrics.json"),
        metrics,
    )

    print("\n" + "=" * 70)
    print("RESULTADO RÁPIDO")
    print("=" * 70)
    print(f"Execuções.............: {metrics['executions']}")
    print(f"Falhas................: {metrics['failures']}")
    print(f"Taxa de sucesso.......: {metrics['success_rate']}%")
    print(f"Duração média.........: {metrics['avg_duration_seconds']} s")
    print(f"Hosts impactados......: {metrics['hosts_impacted']}")
    print(f"Hosts com falha.......: {metrics['failed_hosts']}")
    print(f"Autonomia (proxy).....: {metrics['autonomy']}%")
    print("\nTop 10:")
    for item in metrics["top_30"]:
        print(
            f"  - {item['name']}: "
            f"{item['executions']} execuções | "
            f"{item['success_rate']}% sucesso"
        )

    print("\nArquivos:")
    print(f"  {args.output_dir}/jobs.json")
    print(f"  {args.output_dir}/job_host_summaries.json")
    print(f"  {args.output_dir}/platform_health.json")
    print(f"  {args.output_dir}/quick_metrics.json")


if __name__ == "__main__":
    main()
