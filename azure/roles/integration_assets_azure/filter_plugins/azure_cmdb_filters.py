# =============================================================================
# Filter Plugin: Transformacao Azure -> Jira Assets
# =============================================================================
# Este modulo contem funcoes para transformar dados do Azure (AAP inventory)
# para o formato esperado pelo Jira Assets (CMDB).
# =============================================================================

from __future__ import absolute_import, division, print_function 
__metaclass__ = type
import json

def search_attribute(value, object_attribute_map):
    """Busca um atributo no mapeamento pela chave_cloud."""
    return list(filter(lambda x: x.get("chave_cloud") == value, object_attribute_map))


def extract_os_from_azure(variables):
    """
    Extrai o sistema operacional dos dados do Azure.
    """

    os_disk = variables.get("os_disk", {})
    os_type = os_disk.get("operating_system_type", "").lower()

    if os_type == "windows":
        return "Windows"
    elif os_type == "linux":
        return "Linux"

    os_profile = variables.get("os_profile", {})
    system = os_profile.get("system", "").lower()

    if system == "windows":
        return "Windows"
    elif system == "linux":
        return "Linux"

    image = variables.get("image", {})
    offer = image.get("offer", "").lower()
    publisher = image.get("publisher", "").lower()

    windows_keywords = ["windows", "windowsserver", "win"]
    linux_keywords = [
        "ubuntu",
        "centos",
        "rhel",
        "debian",
        "suse",
        "redhat",
        "linux",
        "alma",
        "rocky",
    ]

    for kw in windows_keywords:
        if kw in offer or kw in publisher:
            return "Windows"

    for kw in linux_keywords:
        if kw in offer or kw in publisher:
            return "Linux"

    return "Linux"


def map_azure_status_to_cmdb(powerstate):
    """Mapeia o powerstate do Azure para o status do CMDB."""
    status_map = {
        "running": "Em uso",
        "starting": "Reservado",
        "deallocating": "Desativado",
        "deallocated": "Desativado",
        "stopped": "Desativado",
        "stopping": "Desativado",
    }
    return status_map.get(powerstate.lower() if powerstate else "", "Em uso")


def is_aks_node(variables):
    """
    Detecta se o host é um nó AKS.
    """

    if not variables:
        return False

    rg = str(variables.get("resource_group") or "").strip()
    if rg.startswith("MC_"):
        return True

    tags = variables.get("tags") or {}
    if not isinstance(tags, dict):
        return False

    if "aks-managed-cluster-name" in tags:
        return True

    for key in tags:
        if str(key).lower().startswith("aks-managed-"):
            return True

    orchestrator = str(tags.get("orchestrator") or "").lower()
    if "kubernetes" in orchestrator:
        return True

    return False


def get_tag(variables, *keys):
    tags = variables.get("tags", {}) or {}
    tags_lower = {str(k).lower(): v for k, v in tags.items()}

    for k in keys:
        v = tags_lower.get(k.lower())
        if v not in (None, ""):
            return v

    return None


def parse_bool_tag(value):
    """Converte string de tag em booleano para campos Boolean do CMDB."""
    if value is None:
        return False
    s = str(value).strip().lower()
    return s in ("true", "sim", "yes", "1", "s", "y")


def determine_ambiente_azure(variables):
    ambiente_tag = get_tag(
        variables,
        "ef_ambiente",
        "environment",
        "ambiente",
    ) or ""

    if not ambiente_tag:
        return None

    ambiente_lower = str(ambiente_tag).lower()

    if any(x in ambiente_lower for x in [
        "nonprod",
        "non-prod",
        "dev",
        "hml",
        "staging",
        "homolog",
        "qa",
        "test",
        "sandbox",
    ]):
        return None

    if any(x in ambiente_lower for x in [
        "prod",
        "prd",
        "production",
    ]):
        return "Produção"

    return None


def determine_owner(sistema_operacional, ambiente, owner_ids=None):
    """
    Determina o Owner padrao da VM segundo as regras do CMDB:
      - Producao + Linux    -> owner_ids['prod_linux']
      - Producao + Windows  -> owner_ids['prod_windows']
      - Nao Producao        -> owner_ids['nao_producao']

    Retorna o objectId (str) do usuario no Object Type 91 (Users).
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

def transform_azure_host(host, modelo_servidor_map=None, vm_size_specs=None,
                         owner_ids=None):
    """
    Transforma os dados de um host Azure (do AAP) para cloud_data.

    Args:
        host: host do AAP.
        modelo_servidor_map: opcional - mapa {vm_size: object_key}.
        vm_size_specs: opcional - mapa {vm_size: {"vcpus": int, "memory_mb": int}}
                       obtido via 'az vm list-sizes -l <location>'.
        owner_ids: opcional - mapa de objectId dos usuarios (Owner).
    """

    # Parsear variables (mesmo padrão do AWS)
    variables_str = host.get("variables", "{}")

    try:
        variables = (
            json.loads(variables_str)
            if isinstance(variables_str, str)
            else variables_str
        )
    except json.JSONDecodeError:
        variables = {}

    if not variables:
        return {}

    # Extrair informações básicas
    name = (
        variables.get("azure_vm_name")
        or host.get("name")
        or variables.get("computer_name", "")
    )

    vmid = variables.get("vmid", "")

    # # Extrair FQDN
    # fqdn = None
    # public_dns_hostnames = variables.get("public_dns_hostnames", [])

    # if public_dns_hostnames and len(public_dns_hostnames) > 0:
    #     fqdn = public_dns_hostnames[0]
    # elif variables.get("public_dns_name"):
    #     fqdn = variables.get("public_dns_name")

    # # Se não tem FQDN real, usar name-vmid para garantir unicidade
    # if fqdn:
    #     name_cloud = name
    # else:
    #     fqdn = name
    #     if vmid:
    #         name_cloud = f"{name}-{vmid}"
    #     else:
    #         name_cloud = name



    # Extrair FQDN
    fqdn = None
    public_dns_hostnames = variables.get("public_dns_hostnames", [])

    if public_dns_hostnames and len(public_dns_hostnames) > 0:
        fqdn = public_dns_hostnames[0]
    elif variables.get("public_dns_name"):
        fqdn = variables.get("public_dns_name")

    # Se não existir FQDN vindo do Azure, criar um identificador único
    if not fqdn:
        fqdn = f"{name}-{vmid}" if vmid else name

    name_cloud = name


    # Extrair IPs
    private_ips = variables.get("private_ipv4_addresses", [])
    public_ips = variables.get("public_ipv4_address", [])

    ips = []

    for ip in private_ips:
        if ip:
            ips.append({"tipo": "privado", "ip": ip})

    for ip in public_ips:
        if ip:
            ips.append({"tipo": "publico", "ip": ip})

    # Extrair disco
    os_disk = variables.get("os_disk", {})
    data_disks = variables.get("data_disks", [])

    # Calcular tamanho total de disco (se disponível)
    disk_size = None

    # VM Size
    vm_size = variables.get("virtual_machine_size", "")

    # CPU/Memoria via Azure API 'az vm list-sizes -l <location>' (quando
    # disponivel no dicionario 'vm_size_specs' passado ao filter).
    vm_size_cpu = None
    vm_size_mem_mb = None
    if vm_size and vm_size_specs:
        specs = vm_size_specs.get(vm_size) or {}
        vm_size_cpu = specs.get("vcpus")
        vm_size_mem_mb = specs.get("memory_mb")

    # Tags Azure
    tag_owner = get_tag(variables, "ef_owner")
    tag_sistema = get_tag(variables, "ef_cmdb")
    tag_produto = get_tag(variables, "ef_produto")
    tag_dr = get_tag(variables, "ef_recuperacao_de_desastre", "ef_dr")
    tag_regiao = get_tag(variables, "ef_regiao", "ef_region")
    tag_iac = get_tag(variables, "ef_iac")

    # Grupo Solucionador
    so_detectado = extract_os_from_azure(variables)

    grupo_solucionador = (
        "CLBR-TI-INFRA-SUPORTE-WINDOWS"
        if so_detectado == "Windows"
        else "CLBR-TI-INFRA-CLOUD-PUBLIC"
    )

    # Ambiente (baseado em tags)
    ambiente = determine_ambiente_azure(variables)

    # Owner (regra fixa por Ambiente + SO - retorna objectId do usuario)
    owner_padrao = determine_owner(so_detectado, ambiente, owner_ids=owner_ids)
    # Montar cloud_data
    cloud_data = {
        # Identificacao
        "name_cloud": name_cloud,
        "fqdn_cloud": fqdn,
        
        # Sistema Operacional
        "sistema_operacional_cloud": so_detectado,

        # Hardware (obtido via 'az vm list-sizes')
        "cpu_count_cloud": str(vm_size_cpu) if vm_size_cpu else None,
        "memoria_ram_cloud": str(vm_size_mem_mb) if vm_size_mem_mb else None,

        # Modelo do Servidor (vm_size -> objectKey via modelo_servidor_map)
        "modelo_servidor_cloud": (
            (modelo_servidor_map or {}).get(vm_size) or vm_size
        ) if vm_size else None,

        # Rede
        "interface_rede_cloud": ips,

        # Status
        "status_cloud": map_azure_status_to_cmdb(variables.get("powerstate", "running")),

        # Tipo/Modelo (valores fixos para Azure)
        "tipo_servidor_cloud": "Virtual",
        "tipo_infraestrutura_cloud": "CLOUD PUBLICA",

        # Datacenter fixo Azure
        "datacenter_cloud": "Azure",

        # Fornecedor (mesmo valor do Datacenter)
        "fornecedor_cloud": "Azure",

        # Discovery
        "status_discovery_cloud": "Running",

        # Booleanos fixos
        "sox_cloud": "false",
        "ipe_cloud": "false",

        # Ambiente (baseado em tags)
        "ambiente_cloud": ambiente,

        # Last User (sempre Ansible, pois esta integracao escreve no CMDB)
        "last_user_cloud": "Ansible",

        # Grupo Solucionador - Infra (fixo por SO)
        "grupo_solucionador_infra_cloud": grupo_solucionador,

        # Owner (regra fixa por Ambiente + SO)
        "owner_cloud": owner_padrao,

        # Tags Azure "ef_*" (metadados; nao substituem o owner padrao acima)
        "sistema_cloud": tag_sistema,
        "produto_cloud": tag_produto,
        "vcenter_cloud": tag_regiao,
        "iac_cloud": tag_iac,
        "disaster_recovery_cloud": parse_bool_tag(tag_dr) if tag_dr is not None else None,

        # Metadados Azure
        "azure_vm_id": variables.get("vmid", ""),
        "azure_resource_group": variables.get("resource_group", ""),
        "azure_location": variables.get("azure_location") or variables.get("location", ""),
        "azure_subscription": extract_subscription_from_id(variables.get("id", "")),
        "azure_tags": variables.get("tags", {}),

        # Conta Cloud
        "conta_cloud_cloud": variables.get("resource_group", ""),
    }

    # Remover valores None ou vazios
    cloud_data = {
        k: v
        for k, v in cloud_data.items()
        if v is not None and v != ""
    }

    return cloud_data


def extract_subscription_from_id(resource_id):
    """Extrai o subscription ID do resource ID do Azure."""
    if not resource_id:
        return ""
    # /subscriptions/XXXX/resourceGroups/...
    parts = resource_id.split("/")
    try:
        idx = parts.index("subscriptions")
        return parts[idx + 1]
    except (ValueError, IndexError):
        return ""


def update_asset(cloud_data, object_attribute_map):
    """
    Transforma cloud_data no formato de payload para criar/atualizar no Jira Assets.
    """
    data = {
        "attributes": [],
        "objectTypeId": 121
    }
    
    for field, value in cloud_data.items():
        if value is None or value == "":
            continue
        
        # Campos de metadados Azure nao sao enviados ao CMDB
        if field.startswith("azure_"):
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
            valores = obj_attr.get("valores", [])

            # Sem lista de "valores" no YAML -> envia o value direto (Jira aceita
            # objectKey/objectId em campos Reference).
            if not valores:
                attribute_entry["objectAttributeValues"] = [{"value": str(value)}]
            else:
                matched = next((v for v in valores if v.get("value") == value), None)

                # Fallback: se o valor recebido nao esta mapeado, usa o "valor_fallback"
                if not matched:
                    valor_fallback = obj_attr.get("valor_fallback")
                    if valor_fallback:
                        matched = next((v for v in valores if v.get("value") == valor_fallback), None)

                if matched:
                    attribute_entry["objectAttributeValues"] = [
                        {"value": str(matched.get("referencedType"))}
                    ]
                else:
                    continue
        
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
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item:
                        attribute_entry["objectAttributeValues"].append(
                            {"value": item}
                        )
                    elif isinstance(item, dict):
                        item_id = item.get("id") or item.get("referencedType")
                        if item_id:
                            attribute_entry["objectAttributeValues"].append(
                                {"value": str(item_id)}
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
            # Para Select, verificar se o valor existe nas opcoes (se definido no mapeamento)
            # Se nao tiver lista de valores validos, aceita qualquer valor
            valores_validos = obj_attr.get("valores_validos", [])
            if valores_validos and value not in valores_validos:
                # Valor nao existe no menu, pular este atributo
                continue
            attribute_entry["objectAttributeValues"] = [
                {"value": str(value)}
            ]
        
        else:  # text e outros
            attribute_entry["objectAttributeValues"] = [
                {"value": str(value)}
            ]
        
        if attribute_entry["objectAttributeValues"]:
            data["attributes"].append(attribute_entry)
    
    # Pos-processamento: garantir fallback para atributos com "valor_fallback"
    # ou "valor_fixo" que nao foram preenchidos (ex.: tag ausente no host Azure).
    # Permite que qualquer campo declare seu default direto no YAML, sem mexer
    # no transform (Python).
    ids_ja_enviados = {a["objectTypeAttributeId"] for a in data["attributes"]}
    for obj_attr in object_attribute_map:
        attr_id = str(obj_attr.get("id"))
        if attr_id in ids_ja_enviados:
            continue

        valor_default = obj_attr.get("valor_fallback")
        if valor_default is None:
            valor_default = obj_attr.get("valor_fixo")
        if valor_default is None:
            continue

        tipo = obj_attr.get("tipo")

        # Tipo objeto: traduzir o "value" para o "referencedType" via lista valores
        if tipo == "objeto":
            valores = obj_attr.get("valores", [])
            matched = next((v for v in valores if v.get("value") == valor_default), None)
            if matched:
                data["attributes"].append({
                    "objectTypeAttributeId": attr_id,
                    "objectAttributeValues": [{"value": str(matched.get("referencedType"))}]
                })
        # Tipo boolean: enviar "true"/"false"
        elif tipo == "boolean":
            data["attributes"].append({
                "objectTypeAttributeId": attr_id,
                "objectAttributeValues": [{"value": str(bool(valor_default)).lower()}]
            })
        # Tipos text/select/integer: enviar o valor como string
        elif tipo in ("text", "select", "integer"):
            data["attributes"].append({
                "objectTypeAttributeId": attr_id,
                "objectAttributeValues": [{"value": str(valor_default)}]
            })

    return data


def batch_transform_hosts(hosts, modelo_servidor_map=None, vm_size_specs=None,
                          owner_ids=None):

    results = []

    for host in hosts:

        if not host.get("enabled", True):
            continue

        variables_str = host.get("variables", "{}")

        try:
            variables = (
                json.loads(variables_str)
                if isinstance(variables_str, str)
                else variables_str
            )
        except json.JSONDecodeError:
            variables = {}

        if is_aks_node(variables):
            continue

        tags = variables.get("tags") or {}

        if not isinstance(tags, dict):
            continue

        tags_lower = {str(k).lower(): v for k, v in tags.items()}

        if not str(tags_lower.get("ef_cmdb", "")).strip():
            continue

        cloud_data = transform_azure_host(
            host,
            modelo_servidor_map=modelo_servidor_map,
            vm_size_specs=vm_size_specs,
            owner_ids=owner_ids,
        )

        if cloud_data.get("name_cloud"):
            results.append(cloud_data)

    return results


class FilterModule(object):
    """Ansible filter plugin para transformacao Azure -> Jira Assets."""
    
    def filters(self):
        return {
            'update_asset_azure': update_asset,
            'transform_azure_host': transform_azure_host,
            'batch_transform_azure_hosts': batch_transform_hosts,
            'extract_os_from_azure': extract_os_from_azure,
            'map_azure_status_to_cmdb': map_azure_status_to_cmdb,
            'determine_owner': determine_owner,
            'extract_subscription_from_id': extract_subscription_from_id,
            'is_aks_node': is_aks_node,
            'search_attribute_azure': search_attribute,
        }


