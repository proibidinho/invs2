#!/usr/bin/env python3

import argparse
import json
import subprocess
import yaml

# Manter esta lista alinhada aos vm_size efetivamente utilizados no projeto.
tamanhos_desejados = [
    "Standard_B1s",
    "Standard_B2s",
    "Standard_B2ms",
    "Standard_B2as_v2",
    "Standard_B4ms",
    "Standard_B4as_v2",
    "Standard_D2s_v3",
    "Standard_D4_v2",
    "Standard_D4s_v3",
    "Standard_D8s_v3",
    "Standard_D32as_v4",
    "Standard_DS3_v2",
    "Standard_E2as_v4",
    "Standard_F2s_v2",
    "Standard_F4s",
    "Standard_F4s_v2",
    "Standard_F8s_v2",
    "Standard_F16s_v2",
]

parser = argparse.ArgumentParser(
    description="Coleta CPU e memoria dos tamanhos de VM Azure."
)
parser.add_argument(
    "--location",
    default="brazilsouth",
    help="Regiao Azure usada na consulta (default: brazilsouth).",
)
parser.add_argument(
    "--output",
    default="azure_vm_specs.yml",
    help="Arquivo YAML de saida (default: azure_vm_specs.yml).",
)
args = parser.parse_args()

print(f"Consultando Azure na regiao {args.location}...")

cmd = [
    "az",
    "vm",
    "list-sizes",
    "--location",
    args.location,
    "--output",
    "json",
]

data = json.loads(subprocess.check_output(cmd, text=True))
por_nome = {item["name"]: item for item in data}

resultado = {}
nao_encontrados = []

for nome in tamanhos_desejados:
    item = por_nome.get(nome)
    if not item:
        nao_encontrados.append(nome)
        continue

    cpu = item["numberOfCores"]
    memoria = item["memoryInMb"] / 1024

    if float(memoria).is_integer():
        memoria = int(memoria)

    resultado[nome] = {
        "cpu": cpu,
        "memory_gb": memoria,
    }

resultado = dict(sorted(resultado.items()))

with open(args.output, "w", encoding="utf-8") as f:
    yaml.safe_dump(
        {"azure_vm_specs": resultado},
        f,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )

print(f"Modelos encontrados: {len(resultado)}")
print(f"Arquivo gerado: {args.output}")

if nao_encontrados:
    print("Modelos nao encontrados nesta regiao:")
    for nome in nao_encontrados:
        print(f"  - {nome}")
