# =============================================================================
# Filter Plugin: Transformação GCP → Jira Assets
# =============================================================================
# Funções para transformar dados do Google Cloud Platform para o formato
# esperado pelo Jira Assets (CMDB)
# =============================================================================

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import json
import re
from typing import Dict, List, Any, Optional


def search_attribute(value: str, object_attribute_map: List[Dict]) -> List[Dict]:
    """
    Busca um atributo no mapeamento pela chave_cloud.

    Args:
        value: Valor da chave_cloud a buscar
        object_attribute_map: Lista de mapeamentos de atributos

    Returns:
        Lista de atributos encontrados
    """
    return list(filter(lambda x: x.get("chave_cloud") == value, object_attribute_map))


def extract_os_from_license(license_url: str) -> str:
    """
    Extrai o sistema operacional a partir da URL de licença do GCP.

    Args:
        license_url: URL da licença (ex: .../debian-cloud/global/licenses/debian-12-bookworm)

    Returns:
        Nome do SO normalizado (Linux, Windows, Unix)
    """
    if not license_url:
        return "Linux"  # Default

    license_lower = license_url.lower()

    # Windows
    if "windows" in license_lower:
        return "Windows"

    # Linux variants
    linux_patterns = [
        "debian", "ubuntu", "centos", "rhel", "red-hat", "suse",
        "rocky", "alma", "fedora", "cos", "container-optimized"
    ]
    for pattern in linux_patterns:
        if pattern in license_lower:
            return "Linux"

    # Unix
    if "freebsd" in license_lower:
        return "Unix"

    return "Linux"  # Default


def extract_zone_from_url(zone_url: str) -> str:
    """
    Extrai o nome da zona a partir da URL completa.

    Args:
        zone_url: URL completa (ex: .../zones/southamerica-east1-c)

    Returns:
        Nome da zona (ex: southamerica-east1-c)
    """
    if not zone_url:
        return ""

    # Extrai a última parte da URL
    parts = zone_url.rstrip('/').split('/')
    return parts[-1] if parts else ""


def extract_project_from_url(url: str) -> str:
    """
    Extrai o project ID de uma URL do GCP.

    Args:
        url: URL do GCP (ex: .../projects/claro-infracloud/...)

    Returns:
        Project ID
    """
    if not url:
        return ""

    match = re.search(r'/projects/([^/]+)/', url)
    return match.group(1) if match else ""


def extract_machine_type_name(machine_type_url: str) -> str:
    """
    Extrai o nome do machine type da URL.

    Args:
        machine_type_url: URL completa do machine type

    Returns:
        Nome do machine type (ex: e2-medium)
    """
    if not machine_type_url:
        return ""

    parts = machine_type_url.rstrip('/').split('/')
    return parts[-1] if parts else ""


def map_gcp_status_to_cmdb(gcp_status: str) -> str:
    """
    Mapeia o status do GCP para o status do CMDB.

    Args:
        gcp_status: Status da instância GCP

    Returns:
        Status correspondente no CMDB
    """
    status_map = {
        "RUNNING": "Em uso",
        "STAGING": "Reservado",
        "PROVISIONING": "Reservado",
        "PENDING": "Em preparação",
        "TERMINATED": "Desativado",
        "STOPPED": "Desativado",
        "SUSPENDED": "Desativado",
        "STOPPING": "Desativado",
        "SUSPENDING": "Desativado",
    }
    return status_map.get(gcp_status, "Em uso")


def determine_ambiente(project_name: str) -> Optional[str]:
    """
    Determina o Ambiente com base no nome do projeto GCP.
    - Se contém "nonprod" ou "non-prod" → None (não preencher)
    - Qualquer outro caso → "Produção"
    """
    if not project_name:
        return "Produção"
    
    project_lower = project_name.lower()
    
    if "nonprod" in project_lower or "non-prod" in project_lower:
        return None
    
    return "Produção"


def determine_owner(sistema_operacional: str, ambiente: Optional[str],
                    owner_ids: Optional[Dict] = None) -> Optional[str]:
    """
    Determina o Owner padrao da VM segundo as regras do CMDB:
      - Producao + Linux    -> owner_ids['prod_linux']
      - Producao + Windows  -> owner_ids['prod_windows']
      - Nao Producao        -> owner_ids['nao_producao']

    Retorna o objectId (str) do usuario no Object Type 91 (Users), pronto
    para ser enviado como referencia ao Jira Assets. Se 'owner_ids' nao for
    fornecido, usa os IDs padrao configurados no vars/main.yml.
    """
    ids = owner_ids or {}
    ambiente_norm = str(ambiente or "").strip().lower()
    is_producao = ambiente_norm in (
        "produção", "producao", "produccao", "production", "prod", "prd"
    )

    if not is_producao:
        return str(ids.get("nao_producao")) if ids.get("nao_producao") else None

    if str(sistema_operacional or "").strip().lower() == "windows":
        return str(ids.get("prod_windows")) if ids.get("prod_windows") else None

    return str(ids.get("prod_linux")) if ids.get("prod_linux") else None


def transform_gcp_instance(instance_data: Dict, machine_type_data: Dict = None,
                           owner_ids: Optional[Dict] = None) -> Dict:
    """
    Transforma os dados de uma instância GCP para o formato cloud_data.

    Args:
        instance_data: JSON da instância GCP (gcloud compute instances describe)
        machine_type_data: JSON do machine type (gcloud compute machine-types describe)
        owner_ids: opcional - mapa {'prod_linux','prod_windows','nao_producao'}
                   com os objectId dos usuarios no Object Type 91 (Users).

    Returns:
        Dicionário no formato cloud_data para o playbook
    """
    # Extrair informações básicas
    name = instance_data.get("name", "")
    zone = extract_zone_from_url(instance_data.get("zone", ""))
    project = extract_project_from_url(instance_data.get("selfLink", ""))

    # Extrair informações de disco
    disks = instance_data.get("disks", [])
    boot_disk = disks[0] if disks else {}
    licenses = boot_disk.get("licenses", [])
    license_url = licenses[0] if licenses else ""
    disk_size = boot_disk.get("diskSizeGb", "0")

    # Extrair informações de rede
    network_interfaces = instance_data.get("networkInterfaces", [])
    ips = []
    for nic in network_interfaces:
        private_ip = nic.get("networkIP")
        if private_ip:
            ips.append({"tipo": "privado", "ip": private_ip})

        access_configs = nic.get("accessConfigs", [])
        for ac in access_configs:
            public_ip = ac.get("natIP")
            if public_ip:
                ips.append({"tipo": "publico", "ip": public_ip})

    # Extrair informações do machine type
    memory_mb = 0
    guest_cpus = 0
    machine_type_name = extract_machine_type_name(instance_data.get("machineType", ""))

    if machine_type_data:
        memory_mb = machine_type_data.get("memoryMb", 0)
        guest_cpus = machine_type_data.get("guestCpus", 0)

    # Extrair labels
    labels = instance_data.get("labels", {})

    # Extrair cpuPlatform
    cpu_platform = instance_data.get("cpuPlatform", "")
    
    # Determinar Ambiente
    ambiente = determine_ambiente(project)

    # Determinar Owner com base no ambiente + SO (retorna objectId do usuario)
    so_normalizado = extract_os_from_license(license_url)
    owner = determine_owner(so_normalizado, ambiente, owner_ids=owner_ids)

    # Montar cloud_data
    cloud_data = {
        # Conta Cloud (nome do projeto GCP)
        "conta_cloud_cloud": project if project else None,
        
        # CPU Platform (para buscar/criar objeto CPU)
        "cpu_platform_cloud": cpu_platform if cpu_platform else None,
        
        # Ambiente
        "ambiente_cloud": ambiente,

        # Owner (regra fixa por ambiente + SO)
        "owner_cloud": owner,

        # Identificação
        "name_cloud": name,
        "fqdn_cloud": f"{name}.{zone}.c.{project}.internal" if name and zone and project else name,

        # Sistema Operacional
        "sistema_operacional_cloud": so_normalizado,

        # Hardware
        "memoria_ram_cloud": str(memory_mb) if memory_mb else None,
        "cpu_count_cloud": str(guest_cpus) if guest_cpus else None,
        "capacidade_disco_cloud": str(disk_size) if disk_size else None,

        # Rede
        "interface_rede_cloud": ips,

        # Status
        "status_cloud": map_gcp_status_to_cmdb(instance_data.get("status", "RUNNING")),

        # Tipo/Modelo
        "tipo_servidor_cloud": "Cloud Pública",
        #"modelo_servidor_cloud": "VMware Virtual Platform",
        "tipo_infraestrutura_cloud": "MAQUINA VIRTUAL",

        # Localização
        "datacenter_cloud": "Google Cloud",
        "projeto_gcp": project,
        "zona_gcp": zone,

        # Discovery
        "status_discovery_cloud": "Running",

        # Booleanos fixos
        "sox_cloud": "false",
        "ipe_cloud": "false",

        # Metadados GCP
        "gcp_instance_id": instance_data.get("id", ""),
        "gcp_self_link": instance_data.get("selfLink", ""),
        "gcp_creation_timestamp": instance_data.get("creationTimestamp", ""),
        "gcp_labels": labels,

        # Labels mapeáveis (se existirem)
        "sistema_cloud": labels.get("system") or labels.get("app"),
        "unidade_negocio_cloud": labels.get("business_unit") or labels.get("bu"),
    }

    # Remover valores None
    cloud_data = {k: v for k, v in cloud_data.items() if v is not None}

    return cloud_data


def update_asset(cloud_data: Dict, object_attribute_map: List[Dict]) -> Dict:
    """
    Transforma cloud_data no formato de payload para criar/atualizar no Jira Assets.

    Args:
        cloud_data: Dados transformados da cloud
        object_attribute_map: Mapeamento de atributos

    Returns:
        Payload para a API do Jira Assets
    """
    data = {
        "attributes": [],
        "objectTypeId": 121
    }

    for field, value in cloud_data.items():
        if value is None or value == "":
            continue

        # Buscar o atributo no mapeamento
        obj_attr_list = search_attribute(field, object_attribute_map)

        if not obj_attr_list:
            continue

        obj_attr = obj_attr_list[0]
        attr_type = obj_attr.get("tipo", "text")
        attr_id = str(obj_attr.get("id"))

        attribute_entry = {
            "objectTypeAttributeId": attr_id,
            "objectAttributeValues": []
        }

        # Processar conforme o tipo do atributo
        if attr_type == "objeto":
            # Buscar o valor referenciado
            valores = obj_attr.get("valores", [])
            matched = next((v for v in valores if v.get("value") == value), None)

            if matched:
                attribute_entry["objectAttributeValues"] = [
                    {"value": str(matched.get("referencedType"))}
                ]
            else:
                continue  # Pular se não encontrar valor válido

        elif attr_type == "status":
            valores = obj_attr.get("valores", [])
            matched = next((v for v in valores if v.get("value") == value), None)

            if matched:
                attribute_entry["objectAttributeValues"] = [
                    {"value": str(matched.get("referencedType"))}
                ]
            else:
                continue

        elif attr_type == "objeto_lista":
            # Para listas de objetos (ex: Interface de Rede)
            # value pode ser: ['2877663', '2877664'] ou [{'id': '123'}, ...]
            if isinstance(value, list) and value:
                for item in value:
                    item_str = None
                    if isinstance(item, str):
                        item_str = item.strip()
                    elif isinstance(item, (int, float)):
                        item_str = str(int(item))
                    elif isinstance(item, dict):
                        item_str = str(item.get("id") or item.get("referencedType") or "")

                    if item_str:
                        attribute_entry["objectAttributeValues"].append(
                            {"value": item_str}
                        )

            if not attribute_entry["objectAttributeValues"]:
                continue

        elif attr_type == "boolean":
            attribute_entry["objectAttributeValues"] = [
                {"value": str(value).lower()}
            ]

        elif attr_type == "integer":
            attribute_entry["objectAttributeValues"] = [
                {"value": str(value)}
            ]

        elif attr_type == "select":
            # Para campos select, verificar se o valor é uma opção válida
            opcoes = obj_attr.get("opcoes", [])
            if opcoes and value not in opcoes:
                valor_default = obj_attr.get("valor_default")
                if valor_default:
                    value = valor_default
                else:
                    continue

            attribute_entry["objectAttributeValues"] = [
                {"value": str(value)}
            ]

        else:  # text e outros
            attribute_entry["objectAttributeValues"] = [
                {"value": str(value)}
            ]

        # Adicionar apenas se tiver valores
        if attribute_entry["objectAttributeValues"]:
            data["attributes"].append(attribute_entry)

    return data


def prepare_network_interface_payload(ip: str, tipo: str = "privado") -> Dict:
    """
    Prepara o payload para criar uma Interface de Rede no Jira Assets.

    Args:
        ip: Endereço IP
        tipo: Tipo do IP (privado/publico)

    Returns:
        Payload para criar objeto Interface de Rede
    """
    # Object Type ID 230 = Interface de Rede
    return {
        "objectTypeId": 230,
        "attributes": [
            {
                "objectTypeAttributeId": "XXXX",  # ID do atributo Name
                "objectAttributeValues": [{"value": ip}]
            }
        ]
    }


def prepare_datacenter_payload(name: str) -> Dict:
    """
    Prepara o payload para criar um Datacenter no Jira Assets.

    Args:
        name: Nome do datacenter (ex: GCP-southamerica-east1-c)

    Returns:
        Payload para criar objeto Datacenter
    """
    # Object Type ID 152 = Datacenter
    return {
        "objectTypeId": 152,
        "attributes": [
            {
                "objectTypeAttributeId": "XXXX",  # ID do atributo Name
                "objectAttributeValues": [{"value": name}]
            }
        ]
    }


def compare_instances(gcp_instances: List[Dict], cmdb_instances: List[Dict]) -> Dict:
    """
    Compara instâncias do GCP com registros do CMDB para determinar ações.

    Args:
        gcp_instances: Lista de instâncias do GCP
        cmdb_instances: Lista de servidores do CMDB

    Returns:
        Dicionário com listas de ações: criar, atualizar, desativar
    """
    gcp_names = {inst.get("name") for inst in gcp_instances}
    cmdb_names = {inst.get("name") for inst in cmdb_instances}

    # Determinar ações
    to_create = gcp_names - cmdb_names
    to_update = gcp_names & cmdb_names
    to_deactivate = cmdb_names - gcp_names

    # Mapear instâncias
    gcp_by_name = {inst.get("name"): inst for inst in gcp_instances}
    cmdb_by_name = {inst.get("name"): inst for inst in cmdb_instances}

    return {
        "criar": [gcp_by_name[name] for name in to_create],
        "atualizar": [
            {"gcp": gcp_by_name[name], "cmdb": cmdb_by_name[name]}
            for name in to_update
        ],
        "desativar": [cmdb_by_name[name] for name in to_deactivate],
        "resumo": {
            "total_gcp": len(gcp_instances),
            "total_cmdb": len(cmdb_instances),
            "a_criar": len(to_create),
            "a_atualizar": len(to_update),
            "a_desativar": len(to_deactivate)
        }
    }


def batch_transform_instances(instances: List[Dict], machine_types: Dict = None,
                              owner_ids: Optional[Dict] = None) -> List[Dict]:
    """
    Transforma uma lista de instâncias GCP para o formato cloud_data.

    Args:
        instances: Lista de instâncias do GCP
        machine_types: Dicionário de machine types por nome
        owner_ids: opcional - mapa de objectId dos usuarios (Owner)

    Returns:
        Lista de cloud_data transformados
    """
    results = []
    machine_types = machine_types or {}

    for instance in instances:
        mt_name = extract_machine_type_name(instance.get("machineType", ""))
        mt_data = machine_types.get(mt_name, {})

        cloud_data = transform_gcp_instance(instance, mt_data, owner_ids=owner_ids)
        results.append(cloud_data)

    return results


class FilterModule(object):
    """Ansible filter plugin para transformação GCP → Jira Assets."""

    def filters(self):
        return {
            'update_asset': update_asset,
            'transform_gcp_instance': transform_gcp_instance,
            'batch_transform_instances': batch_transform_instances,
            'extract_os_from_license': extract_os_from_license,
            'extract_zone_from_url': extract_zone_from_url,
            'extract_project_from_url': extract_project_from_url,
            'extract_machine_type_name': extract_machine_type_name,
            'map_gcp_status_to_cmdb': map_gcp_status_to_cmdb,
            'determine_owner': determine_owner,
            'compare_instances': compare_instances,
            'search_attribute': search_attribute,
        }