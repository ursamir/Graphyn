# Graphyn Market Readiness Roadmap

This roadmap converts current platform strengths into a mature, market-ready product plan.

## Improved Prompt (Reusable)

Use this prompt for future planning tasks:

> "Using the codebase as source of truth (no assumptions), produce a market-readiness execution plan for Graphyn.  
> Include reliability, UX, security, deployment, observability, ecosystem, and commercialization.  
> For each area define objective, user value, acceptance criteria, dependencies, risks, sequence, and KPIs.  
> Convert into phased roadmap milestones (P0/P1/P2) with validation gates and release criteria."

## Objective

Deliver a production workflow platform for typed DAG pipelines (GraphIR) that is safe, operable, and usable across SDK, CLI, API, MCP, and UI.

## Who Uses It

- ML engineers building data/training/inference workflows.
- Platform teams operating shared workflow services.
- AI agent teams using MCP for autonomous pipeline actions.
- Product teams relying on templates and repeatable run operations.
- Enterprise teams requiring governance, auditability, and deploy controls.

## Market-Ready Feature Plan

## 1) Core Reliability

- Event-driven shutdown hardening (no segfault/hang after cancel).
- Regression suite for DAG topology, partial execution, replay, resume, parallel.
- Plugin loader hardening against stale cache/module edge cases.

Acceptance:
- 22/22 examples pass repeatedly on real data.
- No crash exits in soak tests.
- No P0 regressions in CI.

## 2) Product UX

- IR-native Graphyn console (`graphyn-ui/`) — Builder + Runs + Artifacts + Plugins + Templates + Data + Projects + System.
- Template version lifecycle (create/promote/rollback).
- Unified run-debug UX (status + debug-report + lineage/replay).

Acceptance:
- Complex GraphIR round-trips without fidelity loss.
- Template promotion path works across environments.
- UI product identity is Graphyn (domain-agnostic), not audio-only.

## 3) Security and Governance

- Production-safe auth defaults (fail-closed outside dev profiles).
- RBAC for run/control/artifact/template actions.
- Full audit log for API/MCP control-plane operations.

Acceptance:
- Role matrix enforced for privileged operations.
- Complete actor/action/run audit trail.

## 4) Deployment and Infrastructure

- Official Docker image + compose + Helm chart.
- Multi-worker coordination for run status/control.
- Storage profiles for artifacts/runs/provenance.

Acceptance:
- Reproducible staging/prod deploy playbooks.
- Consistent run control in clustered deployments.

## 5) Observability and SRE

- OpenTelemetry tracing/metrics integration.
- Health/readiness/performance endpoints.
- Error taxonomy with actionable alerts.

Acceptance:
- SLO dashboards for run success and latency.
- Reduced MTTR via structured alerts.

## 6) Ecosystem and Extensibility

- Plugin quality gates (lint/test/compat checks).
- Signed/versioned plugin index path.
- First-party non-audio packs (CSV/text/image) to prove domain-agnostic story.

Acceptance:
- Low plugin install/runtime failure rate.
- Clear compatibility matrix across releases.

## 7) DX, Docs, and Commercial Readiness

- Doc-code sync checks in release gates.
- Role-based onboarding (ML engineer, platform ops, agent integrator).
- Packaging matrix (community vs enterprise features/support).

Acceptance:
- Zero stale critical docs at release time.
- Faster activation from install to first successful pipeline.

## Roadmap Phases

## P0 (0-6 weeks): Trust and Stability

- Fix event-driven shutdown crash path.
- Add plugin cache self-healing for startup loader.
- Complete reliability regressions and CI gates.
- Lock auth defaults and deployment warnings.
- Freeze docs as source-of-truth with validation checks.

Exit gate:
- 22/22 examples pass on real data in repeated CI runs.

## P1 (6-12 weeks): Productization

- IR-native UI parity.
- Deployment bundles and ops playbooks.
- Enhanced run-debug workflows and template lifecycle.
- OTel metrics/traces baseline.

Exit gate:
- Pilot users operate without backend-code-only workflows.

## P2 (3-6 months): Scale and Enterprise

- RBAC + audit trail + policy controls.
- Multi-worker orchestration robustness.
- Plugin index ecosystem and governance.
- Commercial packaging and support model.

Exit gate:
- Enterprise readiness review passes for security, operability, and governance.
