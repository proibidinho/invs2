# =============================================================================
# Filter Plugin: Transformação GCP → Jira Assets
# =============================================================================
# Segue o mesmo padrao dos filters finais de Azure e AWS:
#   host (AAP)
#     -> transform_gcp_host
#     -> cloud_data
#     -> batch_transform_gcp_hosts
#     -> object_attribute_map
#     -> update_asset
#     -> Jira Assets
# =============================================================================

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import json
from typing import Dict, List, Optional


def search_attribute(value: str, object_attribute_map: List[Dict]) -> List[Dict]:
    """Busca um atributo no mapeamento pela chave_cloud."""
    return list(filter(lambda x: x.get("chave_cloud") == value, object_attribute_map))


def map_gcp_status_to_cmdb(gcp_status: str) -> str:
    """Mapeia o status do GCP para o status do CMDB."""
    status_map = {
        "RUNNING": "Em uso",
        "STAGING": "Reservado",
        "PROVISIONING": "Reservado",
        "PENDING": "Em preparação",
        "STOPPED": "Desativado",
        "STOPPING": "Desativado",
        "SUSPENDED": "Desativado",
        "SUSPENDING": "Desativado",
        "TERMINATED": "Desativado",
    }
    return status_map.get((gcp_status or "").upper(), "Em uso")


def extract_os_from_gcp(host: Dict) -> str:
    """
    Extrai o Sistema Operacional a partir de disks[0].licenses[0].
    Ex.: .../licenses/debian-12-bookworm -> Linux
         .../licenses/windows-2019-dc    -> Windows
    """
    disks = host.get("disks") or []
    license_str = ""
    if disks and isinstance(disks, list):
        licenses = (disks[0] or {}).get("licenses") or []
        if licenses:
            license_str = str(licenses[0] or "").lower()

    if not license_str:
        return "Linux"

    if "windows" in license_str:
        return "Windows"

    linux_keywords = [
        "debian", "ubuntu", "centos", "rhel", "red-hat",
        "suse", "rocky", "alma", "fedora", "cos",
        "container-optimized", "linux",
    ]
    for kw in linux_keywords:
        if kw in license_str:
            return "Linux"

    if "freebsd" in license_str:
        return "Unix"

    return "Linux"


# def is_gke_node(host: Dict) -> bool:
#     """
#     Detecta se o host eh um no de cluster GKE (analogo a is_eks/is_aks).
#     Sinais: labels goog-gke-node / goog-k8s-cluster-name, ou tag gke-*.
#     """
#     labels = host.get("labels") or host.get("gcp_labels") or {}
#     if isinstance(labels, dict):
#         for k in labels.keys():
#             k_lower = str(k).lower()
#             if k_lower.startswith("goog-gke-") or k_lower.startswith("goog-k8s-"):
#                 return True

#     tags = (host.get("tags") or {}).get("items") or []
#     for t in tags:
#         if str(t).lower().startswith("gke-"):
#             return True

#     return False

def is_gke_node(host):
    labels = host.get("labels") or host.get("gcp_labels") or {}

    if isinstance(labels, dict):
        for k in labels.keys():
            k = str(k).lower()

            if k.startswith("goog-gke-"):
                return True

            if k.startswith("goog-k8s-"):
                return True

    return False

# def determine_ambiente_gcp(host: Dict) -> Optional[str]:
#     """Determina o Ambiente com base em labels (ef_ambiente / environment)."""
#     labels = host.get("labels") or host.get("gcp_labels") or {}
#     if not isinstance(labels, dict):
#         labels = {}

#     ambiente_tag = (
#         labels.get("ef_ambiente")
#         or labels.get("environment")
#         or labels.get("Environment")
#         or ""
#     )

#     if not ambiente_tag:
#         return None

#     ambiente_lower = str(ambiente_tag).lower()

#     if any(x in ambiente_lower for x in [
#         "nonprod", "non-prod", "dev", "hml", "staging",
#         "homolog", "qa", "test", "sandbox",
#     ]):
#         return None

#     if any(x in ambiente_lower for x in ["prod", "prd", "production"]):
#         return "Produção"

#     return None

def determine_ambiente_gcp(host: Dict) -> Optional[str]:
    """
    Determina o Ambiente com base em labels (ef_ambiente / environment).
    """
    labels = host.get("labels") or host.get("gcp_labels") or {}
    if not isinstance(labels, dict):
        labels = {}

    ambiente_tag = (
        labels.get("ef_ambiente")
        or labels.get("environment")
        or labels.get("Environment")
        or host.get("environment")
        or ""
    )

    ambiente_lower = str(ambiente_tag).strip().lower()

    # Desenvolvimento
    if ambiente_lower in ["dsv", "dev", "desenvolvimento"]:
        return "166232"

    # Homologação
    if ambiente_lower in ["hom", "hml", "homologacao", "homologação"]:
        return "166233"

    # Sem informação
    if not ambiente_lower or ambiente_lower == "undefined":
        return "Produção"

    # Produção
    if ambiente_lower in ["prod", "prd", "production", "producao", "produção"]:
        return "Produção"

    return "Produção"


def parse_bool_tag(value) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in ("true", "sim", "yes", "1", "s", "y")


def transform_gcp_host(host: Dict,
                      modelo_servidor_map: Optional[Dict] = None,
                      gcp_machine_specs: Optional[Dict] = None,
                      owner_ids: Optional[Dict] = None,
                      cpu_platform_map: Optional[Dict] = None) -> Dict:
    """
    Transforma um host GCP (do AAP) em cloud_data.

    Args:
        host: dict do inventario AAP (labels, machine_type, disks, networkInterfaces...)
        modelo_servidor_map: mapa {machine_type: object_key GDA-*}
        gcp_machine_specs:   mapa {machine_type: {cpu, memory_gb}}
        owner_ids:           {prod_linux, prod_windows, nao_producao}
        cpu_platform_map:    mapa {cpuPlatform: objectId} para Reference 232
    """
    if not host or not isinstance(host, dict):
        return {}

    labels = host.get("labels") or host.get("gcp_labels") or {}
    if not isinstance(labels, dict):
        labels = {}

    # --------- Identificacao ---------
    name = str(host.get("name", "")).strip()
    project = host.get("project") or host.get("gcp_project") or ""
    zone = host.get("zone") or ""
    fqdn = ""
    if name and zone and project:
        fqdn = "{}.{}.c.{}.internal".format(name, zone, project)

    # --------- IPs / interfaces de rede ---------
    private_ip = host.get("private_ip") or ""
    public_ip = host.get("public_ip") or ""

    ips = []
    nifs = host.get("networkInterfaces") or []
    if isinstance(nifs, list) and nifs:
        for nif in nifs:
            if not isinstance(nif, dict):
                continue
            nic_ip = nif.get("networkIP")
            if nic_ip:
                ips.append({"tipo": "privado", "ip": nic_ip})
            for ac in (nif.get("accessConfigs") or []):
                if isinstance(ac, dict) and ac.get("natIP"):
                    ips.append({"tipo": "publico", "ip": ac["natIP"]})
    else:
        if private_ip and private_ip not in ("", "N/A", "n/a"):
            ips.append({"tipo": "privado", "ip": private_ip})
        if public_ip and public_ip not in ("", "N/A", "n/a"):
            ips.append({"tipo": "publico", "ip": public_ip})

    # --------- Machine type ---------
    machine_type = host.get("machine_type") or host.get("machineType") or ""
    if isinstance(machine_type, str) and "/" in machine_type:
        machine_type = machine_type.rsplit("/", 1)[-1]

    # --------- CPU / Memoria via gcp_machine_specs ---------
    cpu_count = None
    memoria_ram_mb = None
    if machine_type and gcp_machine_specs:
        spec = gcp_machine_specs.get(machine_type) or {}
        if spec.get("cpu") is not None:
            cpu_count = spec.get("cpu")
        if spec.get("memory_gb") is not None:
            # memory_gb pode ser float (0.6, 1.7, 3.75, 7.5, 9.75). Arredondar.
            memoria_ram_mb = int(round(float(spec.get("memory_gb")) * 1024))

    # --------- CPU Platform (host.cpuPlatform -> Reference 232) ---------
    cpu_platform_raw = host.get("cpuPlatform") or ""
    cpu_platform_id = None
    if cpu_platform_raw and cpu_platform_map:
        cpu_platform_id = cpu_platform_map.get(cpu_platform_raw)

    # --------- Disco ---------
    disks = host.get("disks") or []
    disk_size = None
    if disks and isinstance(disks, list):
        disk_size = (disks[0] or {}).get("diskSizeGb")

    # --------- Sistema Operacional ---------
    so_normalizado = extract_os_from_gcp(host)

    # --------- Ambiente ---------
    ambiente = determine_ambiente_gcp(host)

    # --------- Grupo Solucionador ---------
    grupo_solucionador = (
        "CLBR-TI-INFRA-SUPORTE-WINDOWS"
        if so_normalizado == "Windows"
        else "CLBR-TI-INFRA-CLOUD-PUBLIC"
    )

    # --------- Owner (Ambiente + SO + owner_ids). ef_owner NAO participa. ---------
    owner_usr = None
    if ambiente == "Produção" and owner_ids:
        if so_normalizado == "Linux":
            _oid = owner_ids.get("prod_linux")
        elif so_normalizado == "Windows":
            _oid = owner_ids.get("prod_windows")
        else:
            _oid = None
        if _oid:
            owner_usr = "USR-{}".format(_oid)

    # --------- Sistema (label ef_cmdb -> objectKey) ---------
    sistema_cmdb = str(labels.get("ef_cmdb", "")).strip()
    if sistema_cmdb:
        sistema_cmdb = sistema_cmdb.upper()

    # --------- Disaster Recovery ---------
    dr_bool = parse_bool_tag(
        labels.get("ef_recuperacao_de_desastre") or labels.get("ef_dr")
    )

    # --------- Montar cloud_data ---------
    cloud_data = {
        "conta_cloud_cloud": project if project else None,
        "ambiente_cloud": ambiente,
        "sistema_cloud": sistema_cmdb if sistema_cmdb else None,

        "name_cloud": name if name else None,
        "fqdn_cloud": fqdn if fqdn else None,

        "sistema_operacional_cloud": so_normalizado,

        # Hardware via gcp_machine_specs
        "cpu_count_cloud": str(cpu_count) if cpu_count is not None else None,
        "memoria_ram_cloud": memoria_ram_mb,

        # CPU Platform (Reference Object Type 232) via cpu_platform_map
        "cpu_platform_cloud": str(cpu_platform_id) if cpu_platform_id else None,

        # Owner (Ambiente + SO + owner_ids; USR-*)
        "owner_cloud": owner_usr,

        # Modelo do Servidor (machine_type -> objectKey via modelo_servidor_map)
        "modelo_servidor_cloud": (
            (modelo_servidor_map or {}).get(machine_type) or machine_type
        ) if machine_type else None,

        # Rede
        "interface_rede_cloud": ips if ips else None,

        # Status
        "status_cloud": map_gcp_status_to_cmdb(host.get("status", "RUNNING")),

        # Discovery (fixo)
        "status_discovery_cloud": "Running",

        # Booleanos fixos
        "sox_cloud": "false",
        "ipe_cloud": "false",

        # Disaster Recovery (fallback false)
        "disaster_recovery_cloud": dr_bool,

        # Tipo de Servidor (select)
        "tipo_servidor_cloud": "Cloud Pública",

        # Tipo de Infraestrutura
        "tipo_infraestrutura_cloud": "CLOUD PUBLICA",

        # Datacenter
        "datacenter_cloud": "Google Cloud",

        # Fornecedor
        "fornecedor_cloud": "Google Cloud",

        # Grupo Solucionador - Infra (fixo por SO)
        "grupo_solucionador_infra_cloud": grupo_solucionador,

        # Last User (sempre Ansible)
        "last_user_cloud": "Ansible",

        # Capacidade do disco (opcional)
        "capacidade_disco_cloud": str(disk_size) if disk_size else None,

        # Metadados GCP (prefixo _ nao vao ao CMDB)
        "_gcp_instance_id": host.get("id", ""),
        "_gcp_zone": zone,
        "_gcp_project": project,
        "_gcp_machine_type": machine_type,
    }

    # Remover None/vazios (Dev/HML/nao-prod: owner_cloud=None, portanto omitido)
    cloud_data = {k: v for k, v in cloud_data.items() if v is not None and v != ""}

    return cloud_data


def batch_transform_gcp_hosts(hosts: List[Dict],
                              modelo_servidor_map: Optional[Dict] = None,
                              gcp_machine_specs: Optional[Dict] = None,
                              owner_ids: Optional[Dict] = None,
                              cpu_platform_map: Optional[Dict] = None) -> List[Dict]:
    """Transforma lista de hosts GCP em cloud_data (mesmo padrao Azure/AWS)."""
    results = []

    for host in hosts or []:
        if isinstance(host, dict) and host.get("enabled") is False:
            continue

        if not isinstance(host, dict):
            continue

        # Skip GKE (analogo a AKS/EKS)
        if is_gke_node(host):
            continue

        # Sem label ef_cmdb -> nao vai pro CMDB
        labels = host.get("labels") or host.get("gcp_labels") or {}
        if not isinstance(labels, dict) or not str(labels.get("ef_cmdb", "")).strip():
            continue

        cloud_data = transform_gcp_host(
            host,
            modelo_servidor_map=modelo_servidor_map,
            gcp_machine_specs=gcp_machine_specs,
            owner_ids=owner_ids,
            cpu_platform_map=cpu_platform_map,
        )

        if cloud_data.get("name_cloud"):
            results.append(cloud_data)

    return results


def update_asset(cloud_data: Dict, object_attribute_map: List[Dict]) -> Dict:
    """cloud_data -> payload Jira Assets (mesmo padrao Azure/AWS)."""
    data = {"attributes": [], "objectTypeId": 121}

    for field, value in cloud_data.items():
        if value is None or value == "":
            continue
        if field.startswith("_"):
            continue

        obj_attr_list = search_attribute(field, object_attribute_map)
        if not obj_attr_list:
            continue

        obj_attr = obj_attr_list[0]
        attr_type = obj_attr.get("tipo", "text")
        attr_id = str(obj_attr.get("id"))

        entry = {"objectTypeAttributeId": attr_id, "objectAttributeValues": []}

        if attr_type == "objeto":
            valores = obj_attr.get("valores", [])
            if not valores:
                # Sem lista de valores -> value passa direto (objectKey USR-*, GDA-*, objectId CPU)
                entry["objectAttributeValues"] = [{"value": str(value)}]
            else:
                matched = next((v for v in valores if v.get("value") == value), None)
                if not matched:
                    vf = obj_attr.get("valor_fallback")
                    if vf:
                        matched = next((v for v in valores if v.get("value") == vf), None)
                if matched:
                    entry["objectAttributeValues"] = [
                        {"value": str(matched.get("referencedType"))}
                    ]
                else:
                    continue

        elif attr_type == "status":
            valores = obj_attr.get("valores", [])
            matched = next((v for v in valores if v.get("value") == value), None)
            if matched:
                entry["objectAttributeValues"] = [
                    {"value": str(matched.get("referencedType"))}
                ]
            else:
                continue

        elif attr_type == "objeto_lista":
            # Interface de Rede eh tratada separadamente.
            continue

        elif attr_type == "boolean":
            entry["objectAttributeValues"] = [{"value": str(value).lower()}]

        elif attr_type == "integer":
            entry["objectAttributeValues"] = [{"value": str(value)}]

        elif attr_type == "select":
            valores_validos = obj_attr.get("valores_validos", []) or obj_attr.get("opcoes", [])
            if valores_validos and value not in valores_validos:
                continue
            entry["objectAttributeValues"] = [{"value": str(value)}]

        else:  # text
            entry["objectAttributeValues"] = [{"value": str(value)}]

        if entry["objectAttributeValues"]:
            data["attributes"].append(entry)

    # Fallback / valor_fixo para atributos nao preenchidos (mesmo padrao Azure)
    ids_ja = {a["objectTypeAttributeId"] for a in data["attributes"]}
    for obj_attr in object_attribute_map:
        aid = str(obj_attr.get("id"))
        if aid in ids_ja:
            continue
        default = obj_attr.get("valor_fallback")
        if default is None:
            default = obj_attr.get("valor_fixo")
        if default is None:
            continue

        tipo = obj_attr.get("tipo")
        if tipo == "objeto":
            valores = obj_attr.get("valores", [])
            matched = next((v for v in valores if v.get("value") == default), None)
            if matched:
                data["attributes"].append({
                    "objectTypeAttributeId": aid,
                    "objectAttributeValues": [{"value": str(matched.get("referencedType"))}]
                })
        elif tipo == "boolean":
            data["attributes"].append({
                "objectTypeAttributeId": aid,
                "objectAttributeValues": [{"value": str(bool(default)).lower()}]
            })
        elif tipo in ("text", "select", "integer"):
            data["attributes"].append({
                "objectTypeAttributeId": aid,
                "objectAttributeValues": [{"value": str(default)}]
            })

    return data


class FilterModule(object):
    """Ansible filter plugin GCP → Jira Assets."""

    def filters(self):
        return {
            "update_asset_gcp": update_asset,
            "transform_gcp_host": transform_gcp_host,
            "batch_transform_gcp_hosts": batch_transform_gcp_hosts,
            "extract_os_from_gcp": extract_os_from_gcp,
            "map_gcp_status_to_cmdb": map_gcp_status_to_cmdb,
            "is_gke_node": is_gke_node,
            "determine_ambiente_gcp": determine_ambiente_gcp,
            "search_attribute_gcp": search_attribute,
        }