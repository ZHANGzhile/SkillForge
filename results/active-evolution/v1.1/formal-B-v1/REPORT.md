# Active Acquisition v1.1-B

协议：`a0e86e16229bf895402531bec9119aa2747ec1c18bbbdc63d23627909ff33540`。正式150组，6 worlds × 5 paired seeds × 5 methods。

主统计单位为world-seed。Boundary探针不代表Agent EOC；GPU与LLM新增用量均为0。

| Method | Convergence | RMQ | H0 false convergence | FA | FB | Stable regression |
|---|---:|---:|---:|---:|---:|---:|
| no_adapt | 0.000 | 20.000 | 0 | 144 | 6 | 0 |
| passive | 0.000 | 20.000 | 0 | 144 | 6 | 0 |
| random | 0.067 | 19.600 | 0 | 129 | 6 | 0 |
| active | 0.767 | 8.867 | 0 | 7 | 5 | 0 |
| active_v2 | 0.767 | 8.867 | 0 | 7 | 5 | 0 |

```json
{
  "paired_contrasts": {
    "active": {
      "convergence_rate_difference": {
        "point": 0.0,
        "paired_95": [
          0.0,
          0.0
        ]
      },
      "restricted_mean_queries_difference": {
        "point": 0.0,
        "paired_95": [
          0.0,
          0.0
        ]
      },
      "h0_false_convergence_rate_difference": {
        "point": 0.0,
        "paired_95": [
          0.0,
          0.0
        ]
      }
    },
    "random": {
      "convergence_rate_difference": {
        "point": 0.7000000000000001,
        "paired_95": [
          0.5666666666666667,
          0.8
        ]
      },
      "restricted_mean_queries_difference": {
        "point": -10.733333333333334,
        "paired_95": [
          -12.266666666666666,
          -9.266666666666667
        ]
      },
      "h0_false_convergence_rate_difference": {
        "point": 0.0,
        "paired_95": [
          0.0,
          0.0
        ]
      }
    }
  },
  "joint_efficiency_passed": true,
  "heldout_safety_passed": false,
  "h0_false_convergence_reduced": false,
  "v2_research_claim_passed": false
}
```

不能将错误收敛改记不确定，单独解读为学习效率改善；原始/认证收敛、拒绝和H0均保留在完整数据中。
