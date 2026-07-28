#!/usr/bin/env python3

import json
import subprocess
import yaml

modelos_desejados = [
    # c-family
    "c4.large",
    "c4.xlarge",
    "c4.2xlarge",
    "c5.large",
    "c5.xlarge",
    "c5.2xlarge",
    "c5.4xlarge",
    "c5a.large",
    "c5a.xlarge",
    "c5a.2xlarge",
    "c5n.large",
    "c6a.xlarge",
    "c6a.2xlarge",
    "c6a.4xlarge",
    "c6g.2xlarge",
    "c6i.xlarge",
    "c6i.2xlarge",
    "c6i.4xlarge",
    "c6id.8xlarge",
    "c7g.large",

    # m-family
    "m4.large",
    "m4.4xlarge",
    "m4.10xlarge",
    "m5.large",
    "m5.xlarge",
    "m5.2xlarge",
    "m5.4xlarge",
    "m5.8xlarge",
    "m5a.xlarge",
    "m5ad.xlarge",
    "m5d.large",
    "m6a.large",
    "m6a.xlarge",
    "m6a.2xlarge",
    "m6a.4xlarge",
    "m6g.large",
    "m6i.large",
    "m6i.xlarge",
    "m6i.2xlarge",
    "m6i.4xlarge",
    "m6i.24xlarge",
    "m6id.large",
    "m7a.large",
    "m7g.large",
    "m7i.large",
    "m7i.xlarge",
    "m7i.8xlarge",
    "m7i-flex.large",
    "m7i-flex.xlarge",
    "m7i-flex.2xlarge",

    # r-family
    "r5.xlarge",
    "r5.2xlarge",
    "r5a.large",
    "r5a.xlarge",
    "r5a.2xlarge",
    "r5n.large",
    "r6a.large",
    "r6g.xlarge",
    "r6g.2xlarge",
    "r6g.4xlarge",
    "r6i.large",
    "r6i.2xlarge",
    "r6i.4xlarge",
    "r7a.xlarge",

    # t-family
    "t2.nano",
    "t2.micro",
    "t2.small",
    "t2.medium",
    "t2.large",
    "t2.xlarge",
    "t2.2xlarge",
    "t3.nano",
    "t3.micro",
    "t3.small",
    "t3.medium",
    "t3.large",
    "t3.xlarge",
    "t3.2xlarge",
    "t3a.micro",
    "t3a.small",
    "t3a.medium",
    "t3a.large",
    "t3a.xlarge",
    "t3a.2xlarge",
    "t4g.small",
    "t4g.medium",

    # i-family
    "i4g.xlarge",
    "i4i.large"
]

print("Consultando AWS...")

cmd = [
    "aws",
    "ec2",
    "describe-instance-types",
    "--region",
    "sa-east-1",
    "--instance-types",
    *modelos_desejados,
    "--output",
    "json"
]

data = json.loads(subprocess.check_output(cmd))

resultado = {}

for item in data["InstanceTypes"]:

    nome = item["InstanceType"]

    cpu = item["VCpuInfo"]["DefaultVCpus"]

    memoria = item["MemoryInfo"]["SizeInMiB"] / 1024

    if memoria.is_integer():
        memoria = int(memoria)

    resultado[nome] = {
        "cpu": cpu,
        "memory_gb": memoria
    }

resultado = dict(sorted(resultado.items()))

with open("aws_instance_specs.yml", "w") as f:
    yaml.dump(
        {"aws_instance_specs": resultado},
        f,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True
    )

print(f"Modelos encontrados: {len(resultado)}")
print("Arquivo gerado: aws_instance_specs.yml")