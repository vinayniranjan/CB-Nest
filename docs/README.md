# Documentation

| Document | Audience | Contents |
|---|---|---|
| [AI architecture](ai_architecture.md) | Engineers, reviewers | Architecture diagram, request flows (sequence diagrams), components, model/provider, endpoint contracts, security and design decisions, known limitations |
| [API reference](api_reference.md) | Integrators | Auth, envelope, error codes, every AI endpoint with request/response fields and curl examples, tool → backend API map |
| [Permissions matrix](ai_permissions_matrix.md) | Security, reviewers | Role × capability matrix with the enforcing code and the test that proves each row; column and row scopes |
| [Deployment & operations runbook](deployment.md) | Operators | Topology, configuration, first deploy, upgrades, logs/metrics, secret rotation, backup/restore, scaling, security checklist, troubleshooting |
| [Test report](test_report.md) | Everyone | Results across all test layers, failures found and fixed (root cause → fix → regression test), gaps, how to reproduce |
| [Offline eval results](ai_eval_results.md) | Reviewers | 36-case labelled dataset results |
| [Live eval — Claude](live_eval_report_claude.md) · [Live eval — rule-based](live_eval_report_rule_based.md) | Reviewers | 47 cases against the running production stack, per engine |
| [Learner guide](Learner_Guide.md) · [PRD](PRD.md) · [DB schema](db_tables_samples.md) | Everyone | Original CB Nest documentation |

![Architecture](images/architecture.svg)
