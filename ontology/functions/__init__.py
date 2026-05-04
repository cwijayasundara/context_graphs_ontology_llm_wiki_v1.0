"""Action Type implementations. One function per id in action_types.yaml."""
from .actions import (
    create_customer,
    trigger_purchase_order,
    run_allocation_scenario,
    file_synthesis,
    publish_intel_memo,
    flag_concept_review,
)

REGISTRY = {
    "create_customer": create_customer,
    "trigger_purchase_order": trigger_purchase_order,
    "run_allocation_scenario": run_allocation_scenario,
    "file_synthesis": file_synthesis,
    "publish_intel_memo": publish_intel_memo,
    "flag_concept_review": flag_concept_review,
}
