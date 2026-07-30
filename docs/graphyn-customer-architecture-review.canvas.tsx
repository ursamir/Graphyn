import {
  Callout,
  Card,
  CardBody,
  CardHeader,
  Divider,
  Grid,
  H1,
  H2,
  H3,
  Pill,
  Row,
  Spacer,
  Stack,
  Stat,
  Table,
  Text,
} from "cursor/canvas";

const LAYERS = [
  "Interfaces",
  "RuntimeBackend",
  "Planner / Orchestrator",
  "Node contract + registry",
  "Graph IR",
  "Runs / artifacts / provenance",
  "Plugins",
  "Domain / models",
] as const;

const AREA_ROWS: Array<[string, string, string, "success" | "warning" | "danger"]> = [
  ["app/core", "PASS", "BC split matches docs; IR → backend → orchestrator is coherent", "success"],
  ["app/mcp", "PASS", "15 tools → handlers → get_backend(); agent loop is real", "success"],
  ["app/domain", "PASS", "Thin services; platform must not import (boundary held)", "success"],
  ["app/models", "PASS", "PortDataTypes + ArtifactSerializerRegistry registration correct", "success"],
  ["examples", "PASS", "Real-data suites run end-to-end; one event-driven shutdown caveat remains", "success"],
  ["unit_test", "PASS", "Broad suite with hardening regressions for runtime/API/MCP paths", "success"],
  ["app/api", "PASS", "Routers execute GraphIR through backend; auth/path hardening in place", "success"],
  ["app/cli", "PASS", "Replay and run paths execute through backend entrypoint", "success"],
  ["PluginPackage", "PASS-WITH-GAPS", "Core plugins load; startup cache hygiene issue remains in some environments", "warning"],
  ["docs", "PASS", "Architecture/API/runtime docs aligned to code and known issues", "success"],
  ["audiobuilder", "FAIL", "YAML-primary; rejects fan-in/fan-out; fights IR-canonical promise", "danger"],
];

const ALIGN_ROWS: Array<[string, string, string]> = [
  ["SDK-first Pipeline + Graph IR", "Strong", "Canonical product surface for engineers"],
  ["CLI + MCP parity", "Strong", "Agent/workflow ops are credible without UI"],
  ["Typed DAGs + plugins", "Strong", "Parallel / conditional / event / checkpoint / provenance demoed"],
  ["Audio-deep, domain-agnostic", "Good", "CSV example + PortDataType model support non-audio"],
  ["Frontend-optional", "True", "SDK/CLI/MCP work without audiobuilder"],
  ["General-purpose platform claim", "Partial", "Engine yes; multi-tenant deploy product not yet"],
];

const BLOCKER_ROWS: Array<[string, string, string, "danger" | "warning"]> = [
  ["FE-YAML-1", "High", "UI YAML-primary vs IR-canonical; rejects non-linear graphs", "danger"],
  ["EVENT-DRIVEN-EXIT-1", "Medium", "File-watcher event loop may linger after cancel in some environments", "warning"],
  ["PLUGIN-LOAD-1", "Medium", "Stale installed plugin bytecode can break startup load until cache clear", "warning"],
  ["No deploy story", "High (B2B)", "No Docker/Helm/CI — local process only", "danger"],
];

const MISSING_ROWS: Array<[string, string, string]> = [
  ["Container / Helm deploy", "Missing", "Must ship for any shared env"],
  ["Multi-tenant isolation", "Missing", "Single workspace root"],
  ["SSO / OIDC / RBAC", "Missing", "Optional Bearer only"],
  ["OTel / metrics UX", "Thin", "Logs + NDJSON only"],
  ["Plugin marketplace", "Stub", "Index client exists; no hosted catalog"],
  ["Graph versioning / promotion", "Weak", "Templates exist; no env promotion"],
  ["Remote / K8s backend", "Missing", "LocalPythonBackend only"],
  ["CI templates", "Missing", "Buyer must invent pipeline"],
];

const GTM_ROWS: Array<[string, string]> = [
  ["P0", "IR-native audiobuilder — or officially demote UI"],
  ["P1", "Add CI guardrails for event-driven cancellation/shutdown behavior"],
  ["P1", "Auto-heal stale installed plugin caches at startup"],
  ["P1", "Ship Docker + one-command demo"],
  ["P1", "Named graph versions + OTel/status for multi-worker"],
  ["P2", "OIDC/RBAC + tenants"],
  ["P2", "Hosted plugin index + remote backend"],
  ["P2", "CI templates + support packaging"],
];

export default function GraphynCustomerArchitectureReview() {
  return (
    <Stack gap={24} style={{ maxWidth: 1100, margin: "0 auto", padding: 24 }}>
      <Stack gap={8}>
        <H1>Graphyn — Customer & Architecture Review</H1>
        <Text tone="secondary">
          Independent team + prospective B2B buyer lens · Source: code & docs review · Jul 2026
        </Text>
      </Stack>

      <Callout tone="warning">
        Strong SDK/CLI/MCP engine for typed audio-ML DAGs. Core correctness/auth/backend
        path issues are fixed; remaining blockers are UI IR parity and production packaging.
      </Callout>

      <Grid columns={4} gap={12}>
        <Stat value="1 FAIL" label="Source area (UI)" tone="danger" />
        <Stat value="2 gaps" label="Areas with gaps" tone="warning" />
        <Stat value="8 PASS" label="Solid areas" tone="success" />
        <Stat value="P0×1" label="Top go-to-market blocker" tone="danger" />
      </Grid>

      <Divider />

      <Stack gap={12}>
        <H2>Mental model (what a customer must understand)</H2>
        <Card>
          <CardBody>
            <Stack gap={12}>
              <Text>
                Graphyn is a local-first workflow OS: author a typed DAG as Graph IR
                (`.graph.json`); SDK / CLI / REST / MCP should call `get_backend().execute(graph)`;
                one orchestrator plans waves, runs nodes (retry / cache / checkpoint), and persists
                runs plus content-addressed artifacts. Plugins supply nodes; domain types register
                into platform registries. The UI is optional — and currently the weakest interface.
              </Text>
              <Row gap={8} style={{ flexWrap: "wrap" }}>
                {LAYERS.map((layer) => (
                  <span key={layer}>
                    <Pill tone="neutral" size="sm">
                      {layer}
                    </Pill>
                  </span>
                ))}
              </Row>
              <Text tone="secondary" size="small">
                Bounded contexts: BC1 IR · BC2 Node contract · BC3 Catalog · BC4 Planner · BC5
                Runtime · BC6 Observability & storage
              </Text>
            </Stack>
          </CardBody>
        </Card>
      </Stack>

      <Stack gap={12}>
        <H2>Source-area gate (architecture mental model)</H2>
        <Text tone="secondary" size="small">
          Each product source must pass with a clear mental model of the full architecture.
        </Text>
        <Table
          headers={["Area", "Verdict", "Why"]}
          rows={AREA_ROWS.map(([area, verdict, why]) => [area, verdict, why])}
          rowTone={AREA_ROWS.map((r) => r[3])}
        />
      </Stack>

      <Grid columns={2} gap={16}>
        <Stack gap={12}>
          <H2>Aligns with business goals</H2>
          <Table
            headers={["Goal", "Fit", "Note"]}
            rows={ALIGN_ROWS.map(([goal, fit, note]) => [goal, fit, note])}
          />
        </Stack>
        <Stack gap={12}>
          <H2>Broken promises / blockers</H2>
          <Table
            headers={["Issue", "Sev", "Impact"]}
            rows={BLOCKER_ROWS.map(([id, sev, impact]) => [id, sev, impact])}
            rowTone={BLOCKER_ROWS.map((r) => r[3])}
          />
        </Stack>
      </Grid>

      <Stack gap={12}>
        <H2>Missing features a buyer expects</H2>
        <Table
          headers={["Expectation", "Status", "Why it matters"]}
          rows={MISSING_ROWS.map(([feat, status, why]) => [feat, status, why])}
        />
      </Stack>

      <Stack gap={12}>
        <H2>Go-to-market backlog</H2>
        <Table
          headers={["Pri", "Action"]}
          rows={GTM_ROWS.map(([pri, action]) => [pri, action])}
          rowTone={GTM_ROWS.map(([pri]) =>
            pri === "P0" ? "danger" : pri === "P1" ? "warning" : "info",
          )}
        />
      </Stack>

      <Divider />

      <Stack gap={12}>
        <H2>Two-persona summary</H2>
        <Grid columns={2} gap={12}>
          <Card>
            <CardHeader trailing={<Pill tone="info">Independent team</Pill>}>
              Engineering verdict
            </CardHeader>
            <CardBody>
              <Stack gap={8}>
                <Text>
                  Core architecture is intentional and now consistent with backend execution
                  contracts. The main product risk is still the UI's YAML-first model; either
                  ship IR-native canvas behavior or position UI as non-canonical.
                </Text>
                <H3>Do next</H3>
                <Text size="small" tone="secondary">
                  IR-native UI path → deployment packaging → startup self-healing for plugin cache.
                </Text>
              </Stack>
            </CardBody>
          </Card>
          <Card>
            <CardHeader trailing={<Pill tone="info">Customer</Pill>}>
              Adoption verdict
            </CardHeader>
            <CardBody>
              <Stack gap={8}>
                <Text>
                  Adopt today for SDK/CLI/MCP audio pipelines in a trusted single-tenant environment.
                  Avoid relying on the visual builder for branching DAGs until IR parity ships.
                  Expect to own deploy, SSO, and multi-tenant concerns for now.
                </Text>
                <H3>Buy if…</H3>
                <Text size="small" tone="secondary">
                  You need typed audio DAGs + agent tools now, and can accept local-first ops.
                </Text>
              </Stack>
            </CardBody>
          </Card>
        </Grid>
      </Stack>

      <Spacer height={8} />
      <Text tone="secondary" size="small">
        Detail backlog: docs/KNOWN_ISSUES.md · Architecture: docs/ARCHITECTURE.md
      </Text>
    </Stack>
  );
}
