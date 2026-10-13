"""One fixed common interface instruction, no task-specific tool sequence."""
from skillforge.evolution_schemas import fingerprint
from skillforge.training_data import file_hash
from skillforge.skill_evolution.model import CatalogModel
from skillforge.skill_evolution.runtime import SYSTEM_PROMPT as ORIGINAL_PROMPT
from skillforge.interview_sprint.adapters import bind
from .runtime import PROTOCOL

INTERFACE_INSTRUCTION = """
For a read-only fact-collection request, first use search_skills once with a query
describing the requested goal, if search budget is available. Searching costs one
model decision even when no procedure is found. If no read-only procedure covers
the goal, use primitive reads. Never load a procedure requiring writes.
For a suitable procedure, load the exact returned skill_id and revision, then
execute that loaded skill. Its display name is not an executable alias.
Before issuing a skill action, read its inputs list in catalog.loaded_skills.
Each listed input is REQUIRED in the action's arguments object. Copy each input
key and its actual value from the public task parameters. An empty arguments
object is invalid when the skill has required inputs. Do not invent a value or
omit a required input. The action shape is:
{"type":"skill","name":"<exact loaded skill_id>","arguments":{"<required input key>":"<actual matching value from parameters>"}}.
The placeholders describe the interface, not literal values to send. Use the
actual loaded ID and actual public parameters. Do not search or load again once
the usable exact revision is loaded. After the skill succeeds, stop. If a required
input is unavailable or the procedure does not cover the goal, use the permitted
primitive tools instead. These interface rules do not change authorization or
the public task goal. Return exactly one JSON next action.
"""
SYSTEM_PROMPT = ORIGINAL_PROMPT + INTERFACE_INSTRUCTION


class BindingModel(CatalogModel):
    def __init__(self, config, adapter):
        super().__init__(config, adapter)
        self.settings.update(system_prompt=SYSTEM_PROMPT, prompt_version=PROTOCOL,
            prompt_sha256=fingerprint(SYSTEM_PROMPT), decision_protocol=PROTOCOL,
            catalog_serving_code_hash=file_hash(__file__))

    decide = bind(CatalogModel.decide, {"SYSTEM_PROMPT": SYSTEM_PROMPT})
