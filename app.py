import os
import json
from pathlib import Path

import aws_cdk as cdk

from app_ecosystem.stacks.common_infra import CommonInfraStack
from app_ecosystem.stacks.standard_app import StandardAppStack

# ecs CPU/MEM validation 

_ecs_shapes_file = Path(__file__).parent / "app_ecosystem" / "config" / "ecs_task_cpu_mem.json"
_ECS_TASK_SHAPES = json.loads(_ecs_shapes_file.read_text(encoding="utf-8"))

def _allowed_memories(cpu: int):
    return _ECS_TASK_SHAPES.get(str(cpu), [])
def validate_apps_task_shapes(apps_cfg: dict):
    errors = []
    for app in apps_cfg.get("apps", []):
        name = app.get("name", "<unknown>")
        cpu = app.get("total_task_cpu")
        mem = app.get("total_task_memory")

        if cpu is None or mem is None:
            errors.append(f"[MissingField] app='{name}' missing total_task_cpu or total_task_memory")
            continue

        allowed = _allowed_memories(cpu)
        if not allowed or mem not in allowed:
            preview = allowed[:12] + (["..."] if len(allowed) > 12 else [])
            errors.append(
                f"[Invalid Task Shape] app='{name}' cpu={cpu} memory={mem} not allowed. "
                f"Allowed (MiB): {preview if preview else 'N/A (cpu unsupported)'}"
            )

    if errors:
        raise ValueError("ECS task shape validation failed:\n" + "\n".join(errors))

# Initialise the overarching CDK app (under which all stacks will be created)
cdk_app = cdk.App()

# Initialise common infrastructure stack
# This stack will contain shared resources like VPC, ALB, etc.
network_config_path = os.path.join(
    os.path.dirname(__file__), "app_ecosystem", "config", "network.json"
)
network_config = json.load(open(network_config_path))
common_infra = CommonInfraStack(
    cdk_app, construct_id="CommonInfraStack", network_config=network_config
)

# Initialise a StandardAppStack for each app defined in the apps.json config file
app_configs_json_path = os.path.join(
    os.path.dirname(__file__), "app_ecosystem", "config", "apps.json"
)
app_configs = json.load(open(app_configs_json_path))

# Validate ecs CPU/MEM before create appstack
validate_apps_task_shapes(app_configs)

for app_config in app_configs["apps"]:
    app_stack = StandardAppStack(
        cdk_app,
        construct_id=f"{app_config['name'].title()}Stack",
        app_config=app_config,
        common_infra=common_infra,
    )

cdk_app.synth()
