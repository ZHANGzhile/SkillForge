# P9 proposal validation attribution

Offline diagnosis only; no new model inference or holdout claims.

{"proposals": 4, "full_system_pairs": 48, "decision_pairs": 32, "changes": {"unchanged": 39, "regression": 6, "improvement": 3}, "regression_primary_causes": {"missing_post_write_verification": 5, "invalid_action_schema": 1}}

| Proposal | Pair | Primary cause | Evidence cache |
|---|---:|---|---|
| model-layer\continuous\1\active\activation.json | 1 | missing_post_write_verification | 2dd73eb72f54e9656b8f951d38396e46d448d4c56ad1e154cb8ad889220d170c |
| model-layer\continuous\2\active\activation.json | 1 | missing_post_write_verification | b8ec368cc44b7d454f161e79ff319f4032318f8b36817de02c81b823486f8b36 |
| model-layer\continuous\2\active\activation.json | 7 | missing_post_write_verification | 2ee277b936ac355e68bf41974579c1d3dacb931ef39f5e1de1c95c56448326c5 |
| model-layer\continuous\2\active\activation.json | 9 | missing_post_write_verification | a2f49d9175277fc2b26bd6656125471c97e77014f9de00c13407b23189bfe9b8 |
| model-layer\independent\W3\active\activation.json | 9 | invalid_action_schema | c5fc470e60d68fb9a627f2fd39492f39e2d05f0c05ade2db531144c5cd0bb937 |
| model-layer\independent\W5\active\activation.json | 6 | missing_post_write_verification | e9d4a5ef17a6933349b4ad874a9e13396ed478e5b34943bc3c7fdf662b1996c4 |
