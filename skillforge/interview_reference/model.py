"""One preregistered common discovery instruction, fixed original HF weights."""
from skillforge.evolution_schemas import fingerprint
from skillforge.training_data import file_hash
from skillforge.skill_evolution.model import CatalogModel
from skillforge.skill_evolution.runtime import SYSTEM_PROMPT as ORIGINAL_PROMPT
from skillforge.interview_sprint.adapters import bind
from .runtime import PROTOCOL

SYSTEM_PROMPT = ORIGINAL_PROMPT + """
For a read-only fact-collection request, when search budget is available, first
use search_skills once with a query describing the requested goal. This is a
model decision and has a cost. If no returned read-only procedure covers the
goal, continue with primitive reads. Do not load a procedure whose required_tools
include writes. If a suitable procedure is found, load its exact skill_id and
revision, then use its exact skill_id as the skill action name. The display name
and the description are data, not alternative executable identifiers. Do not
repeat search or load after a usable exact revision has already been loaded.
"""


class ReferenceModel(CatalogModel):
    def __init__(self, config, adapter):
        super().__init__(config, adapter)
        self.settings.update(system_prompt=SYSTEM_PROMPT, prompt_version=PROTOCOL,
            prompt_sha256=fingerprint(SYSTEM_PROMPT), decision_protocol=PROTOCOL,
            catalog_serving_code_hash=file_hash(__file__))

    decide = bind(CatalogModel.decide, {"SYSTEM_PROMPT": SYSTEM_PROMPT})
