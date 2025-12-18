Graph Schema & Knowledge Model Specification
Product: LOGOS – Cognitive Engine + Stakeholder Engagement MVP
________________________________________
1. Introduction
1.1 Purpose
This document specifies the graph schema and knowledge model for LOGOS, covering:
•	How the Platonic / Socratic concepts (Forms, Concepts, Particulars, Agents, Dialectical Lines) are represented in Neo4j.
•	How dynamic, self-describing schema definitions are sourced from the knowledgebase and applied at runtime.
•	How universal stakeholder concepts (stakeholder, relationship, issue, engagement action, risk, outcome, document, project component) map into the graph.
•	Conventions for IDs, provenance, timestamps, scores, and schema evolution.
This is the reference for any component that reads or writes to the LOGOS graph.
1.2 Scope
•	Logical and physical graph schema for Neo4j.
•	Knowledge model conventions (Forms / Concepts / Particulars / Agents).
•	Seed schema for the Stakeholder Engagement MVP, designed to evolve and remain reusable for future modules (contracts, ESG, governance, etc.).
Out of scope: low-level Neo4j deployment details (covered in SAD / runbook).
1.3 Design Principles
•	Universal but extensible: schema works across industries with domain-specific extensions via Concepts and Topics.
•	Self-describing: node and relationship types live in editable knowledgebase YAML and can be added, updated, or deprecated without code changes.
•	Graph-native: model relationships first; keep nodes lean but expressive.
•	Provenance-first: every fact traceable back to sources and processing versions.
•	Socratic: support “why” chains via explainable paths and derived edges (influence, risk, etc.).
•	Stable IDs: deterministic or stable IDs to allow idempotent upserts.
•	Self-describing schema: LOGOS reads node/relationship definitions from `logos/knowledgebase/schema/*.yml` and evolves them at runtime (usage counts, deprecation flags, inferred properties). New labels and relationship types must be registered here, not hardcoded.
1.4 Schema Source of Truth and Evolution
•	Node and relationship type definitions, allowed properties, and concept affinities live in YAML under `logos/knowledgebase/schema/`:
  •	`node_types.yml` – labels, properties, concept_kind, version metadata, usage counts, deprecation flags.
  •	`relationship_types.yml` – relationship types, properties, usage metadata, deprecation flags.
  •	`inference.yml` – property-driven relationship inference rules (e.g., `org_id` ⇒ `WORKS_FOR`).
  •	`rules.yml` – deprecation thresholds (staleness, success score floors).
  •	Schema version is tracked in `logos/knowledgebase/versioning/schema.yml` and is incremented automatically when new labels/relationships are introduced.
•	LOGOS must treat these YAML files as the canonical schema registry:
  •	At startup, load them to configure indexes and validation.
  •	When encountering a new label/relationship, append it to the YAML (usage_count starts at 1, last_used set to processing time) and bump the schema version.
  •	Mark rarely used or low-success entries as `deprecated: true` according to `rules.yml` instead of deleting them in code.
•	All Cypher upserts must be driven by this registry—no fixed `_ALLOWED_RELATIONSHIPS` sets or label-specific upsert functions.
________________________________________
2. Conceptual Knowledge Model
LOGOS uses four main conceptual layers:
1.	Forms
o	Abstract categories of things LOGOS reasons about.
o	Examples: Stakeholder, Organisation, Project, Interaction, Commitment, Issue, Risk, Outcome, Document, Policy, Topic, Agent, ProjectComponent.
2.	Concepts
o	Domain-specific refinements of Forms.
o	Examples: StakeholderType (regulator, community, supplier), RiskCategory, IssueCategory, Topic taxonomy, EngagementActionType.
3.	Particulars
o	Concrete instances: Jane Smith, Acme Pty Ltd, Project IronBridge, Meeting on 2025-03-12, SOC2 Report Commitment #17.
4.	Agents
o	AI agents operating on LOGOS, associated with users and domain profiles.
5.	Dialectical Lines (Reasoning Paths)
o	Relationships and argument structures capturing:
	Influence, causality, justification.
	e.g. (Stakeholder) -[:INFLUENCES {weight}]-> (Stakeholder), (Risk) -[:RESULT_OF]-> (Issue).
In Neo4j terms:
•	Forms and Concepts live primarily as :Concept nodes and sometimes implied by labels.
•	Particulars are standard domain nodes (:Person, :Org, :Project, etc.).
•	Agents are :Agent nodes with relationships to Persons and Concepts.
•	Dialectical Lines are specific relationship types plus explanation paths derived by the reasoning engine.
________________________________________
3. Dynamic Neo4j Schema Model
LOGOS no longer assumes a fixed set of labels or relationship types. The schema is self-describing and evolves through knowledgebase YAML definitions that can be updated at runtime.
3.1 Self-describing schema sources
•	Node and relationship types are defined in knowledgebase YAML (e.g. logos/knowledgebase/concepts/forms.yml, logos/knowledgebase/workflows/pipelines.yml, or schema-specific schema files).
•	Each definition includes:
o	id (unique type identifier).
o	labels (one or more Neo4j labels to apply).
o	properties (recommended keys, hints for validation, defaults).
o	metadata: introduction_version, usage_frequency (rolling count/score), deprecated (boolean/timestamp), last_seen_at, owner (who added it).
o	category flags for Forms vs Particulars vs Concepts and any subtype hints.
•	New types can be added or updated without code changes; LOGOS reads the definitions on startup and can refresh them when knowledgebase files change.
Example (schema_types.yml):
schema:
  nodes:
    - id: person
      labels: ["Person"]
      form: "Stakeholder"
      properties:
        - name: "id"
          required: true
        - name: "name"
        - name: "email"
      metadata:
        introduction_version: "0.5.0"
        usage_frequency: 132
        deprecated: false
  relationships:
    - id: works_for
      type: "WORKS_FOR"
      from: ["Person"]
      to: ["Org"]
      properties:
        - name: "start_date"
        - name: "end_date"
      metadata:
        introduction_version: "0.5.0"
        usage_frequency: 98
        deprecated: false
3.2 Runtime loading and evolution
•	Schema is hydrated from YAML at service start and cached with a change-watch hook so edits are reflected without redeploy.
•	Usage telemetry (writes/reads per type) is fed back into the metadata (usage_frequency, last_seen_at).
•	Deprecated types remain readable but are skipped for new writes; migrations can prune or alias them.
3.3 Neo4j write strategy (generic MERGE)
•	GraphIO builds Cypher dynamically from schema definitions rather than hard-coded labels.
•	Pattern:
(:Interaction)-[:MENTIONS]->(:Topic|:Org|:Person|:Project|:Contract|:Issue|:Risk)
•	Purpose: Connect interactions to entities they mention.
•	Properties:
o	confidence (float, optional).
o	span (string; e.g. snippet/excerpt, optional).
________________________________________
5.8 MADE / REQUESTED (Commitments)
•	Patterns:
o	(:Person)-[:MADE]->(:Commitment) // Using internal owner as maker
o	(:Person)-[:REQUESTED]->(:Commitment)
o	(:Org)-[:REQUESTED]->(:Commitment)
•	Purpose: Model who made and who requested commitments.
•	Properties:
o	role (optional; e.g. owner, delegate).
________________________________________
5.9 RELATES_TO (Commitments, Issues, Risks ↔ Projects/Contracts/Topics)
•	Patterns:
o	(:Commitment)-[:RELATES_TO]->(:Project|:Contract|:Topic|:Issue|:ProjectComponent)
o	(:Issue)-[:RELATED_TO]->(:Project|:Risk|:Topic)
o	(:Risk)-[:RELATED_TO]->(:Project|:Topic)
•	Purpose: Link commitments/issues/risks to the artefacts they concern.
________________________________________
5.10 RAISED_IN / IDENTIFIED_IN
•	Patterns:
o	(:Issue)-[:RAISED_IN]->(:Interaction)
o	(:Risk)-[:IDENTIFIED_IN]->(:Interaction)
•	Purpose: Capture where issues/risks were first discussed.
________________________________________
5.11 RESULTS_IN / ASSOCIATED_WITH (Risk/Outcome/Project)
•	Patterns:
o	(:Risk)-[:RESULTS_IN]->(:Outcome)
o	(:Outcome)-[:ASSOCIATED_WITH]->(:Project|:ProjectComponent)
•	Purpose: Connect realised outcomes back to risks and project components.
________________________________________
5.12 INFLUENCES (Stakeholder influence)
•	Patterns:
o	(:Person)-[:INFLUENCES {weight}]->(:Person)
o	(:Org)-[:INFLUENCES {weight}]->(:Org)
•	Purpose: Represent influence networks (derived or manually set).
•	Properties:
o	weight (float; strength of influence, e.g. 0–1).
o	source (string; derived, manual, etc.).
________________________________________
5.13 ASSISTS (Agent ↔ Person)
•	Pattern: (:Agent)-[:ASSISTS]->(:Person)
•	Purpose: AI agent specifically configured to support a person.
________________________________________
5.14 INSTANCE_OF / PARENT_OF (Concepts)
•	Patterns:
o	(:Node)-[:INSTANCE_OF]->(:Concept) // Node can be any domain node
o	(:Concept)-[:PARENT_OF]->(:Concept)
•	Purpose:
o	Link particulars to Concepts (e.g. Person is INSTANCE_OF StakeholderType “Regulator”).
o	Model concept hierarchies.
________________________________________
5.15 APPLIES_TO (Policy ↔ Project/Contract/etc.)
•	Pattern: (:Policy)-[:APPLIES_TO]->(:Project|:Contract|:Org|:Topic)
•	Purpose: Represent governance applicability.
________________________________________
6. Forms / Concepts / Particulars / Agents Mapping
6.1 Forms
Forms are represented as Concepts of kind Form:
•	Example:
o	(:Concept {id:"form_stakeholder", kind:"Form", name:"Stakeholder"})
•	Domain nodes then INSTANCE_OF the appropriate Form-based Concepts via intermediate Concepts:
o	(:Person)-[:INSTANCE_OF]->(:Concept {kind:"StakeholderType", name:"Community"})
o	This StakeholderType Concept may have [:INSTANCE_OF]->(:Concept {kind:"Form", name:"Stakeholder"}) if you want explicit layering.
Recommendation for MVP:
•	Implement :Concept(kind="StakeholderType" | "RiskCategory" | etc.).
•	Keep explicit kind="Form" Concepts as a design pattern, but you can defer heavy use until needed for more advanced reasoning.
6.2 Concepts
Typical Concept nodes:
•	StakeholderType: Community, Supplier, Regulator, Traditional Owner, etc.
•	RiskCategory: Safety, Schedule, Commercial, ESG, Reputation.
•	IssueCategory: same style as RiskCategory, with finer granularity.
•	OutcomeType: ProjectSuccess, ProjectFailure, CommunityBenefit, etc.
•	TopicGroup: grouping for :Topic nodes.
6.3 Particulars
All domain instances are Particulars:
•	Each :Person, :Org, :Project, :Interaction, :Commitment, etc. is a Particular.
•	Particulars may have INSTANCE_OF relationships to Concepts for classification.
6.4 Agents
•	Each :Agent node is both a Particular (concrete configured agent) and instance of Concept types:
o	(:Agent)-[:INSTANCE_OF]->(:Concept {kind:"Form", name:"Agent"})
o	Optionally also INSTANCE_OF domain-specific agent types (e.g. “StakeholderAdvisorAgent”).
________________________________________
7. Derived / Analytical Structures
7.1 Influence Scores
•	:Person.influence_score and :Org.influence_score:
o	Derived from graph centrality metrics and/or learned models.
•	:INFLUENCES.weight:
o	Derived or manual; used as edge weight in reasoning.
7.2 Risk Scores
•	Node-level risk scores:
o	:Person.risk_score, :Org.risk_score, :Project.risk_score (optional).
•	Commitments and Issues can contribute to these via reasoning rules.
7.3 Materialised Metrics
Initially, keep metrics as node properties.
If you later need time series or multiple metrics per entity:
•	Introduce:
o	(:Metric {id, name, value, measured_at, period, dimension})
o	Connected via (:Node)-[:HAS_METRIC]->(:Metric).
________________________________________
8. Schema Governance & Evolution
8.1 Versioning
•	Maintain a schema version in configuration (not in DB itself).
•	For major schema changes:
o	Document changes in a migration log.
o	Use Cypher migration scripts to add new nodes/relationships/properties.
8.2 Backwards Compatibility
•	Prefer adding new properties/relationships rather than changing semantics of existing ones.
•	Mark deprecated properties/relationships in documentation and avoid new writes to them.
8.3 Domain Extensions
For new domains (e.g. contracts, ESG, governance):
•	Add new Concept nodes and Topic nodes.
•	Extend schema with new relationships only if needed.
•	Avoid duplicating Forms already covered (Stakeholder, Risk, Issue, Outcome, Policy, etc.).
________________________________________
9. Example Cypher Snippets
9.1 Upsert Organisation
MERGE (o:Org {id: $org.id})
SET  o.name        = $org.name,
     o.legal_name  = $org.legal_name,
     o.domain      = $org.domain,
     o.sector      = $org.sector,
     o.type        = $org.type,
     o.updated_at  = datetime(),
     o.last_seen_at = datetime(),
     o.source_uri  = $org.source_uri
ON CREATE SET
     o.created_at   = datetime(),
     o.first_seen_at = datetime(),
     o.created_by    = $user_id;
9.2 Upsert Person & WORKS_FOR
MERGE (p:Person {id: $person.id})
SET  p.name        = $person.name,
     p.email       = $person.email,
     p.title       = $person.title,
     p.type        = $person.type,
     p.updated_at  = datetime(),
     p.last_seen_at = datetime(),
     p.source_uri  = $person.source_uri
ON CREATE SET
     p.created_at    = datetime(),
     p.first_seen_at = datetime(),
     p.created_by    = $user_id;

WITH p
MATCH (o:Org {id: $org_id})
MERGE (p)-[r:WORKS_FOR]->(o)
SET  r.updated_at  = datetime()
ON CREATE SET
     r.created_at  = datetime(),
     r.source_uri  = $person.source_uri;
9.3 Upsert Interaction & Mentions
MERGE (i:Interaction {id: $ix.id})
SET  i.type           = $ix.type,
     i.at             = datetime($ix.at),
     i.subject        = $ix.subject,
     i.summary        = $ix.summary,
     i.sentiment_score = $ix.sentiment,
     i.sentiment_label = $ix.sentiment_label,
     i.source_uri     = $ix.source_uri,
     i.processing_version = $ix.processing_version,
     i.updated_at     = datetime(),
     i.last_seen_at   = datetime()
ON CREATE SET
     i.created_at     = datetime(),
     i.first_seen_at  = datetime(),
     i.created_by     = $user_id;

WITH i, $mentions AS mentions
UNWIND mentions AS m
MATCH (n {id: m.id})
MERGE (i)-[r:MENTIONS]->(n)
SET  r.updated_at = datetime()
ON CREATE SET
     r.created_at = datetime(),
     r.source_uri = $ix.source_uri;
9.4 Upsert Commitment and Linkages
MERGE (c:Commitment {id: $c.id})
SET  c.text        = $c.text,
     c.due_date    = date($c.due_date),
     c.status      = $c.status,
     c.priority    = $c.priority,
     c.updated_at  = datetime(),
     c.last_seen_at = datetime(),
     c.source_uri  = $c.source_uri
ON CREATE SET
     c.created_at   = datetime(),
     c.first_seen_at = datetime(),
     c.created_by    = $user_id;

WITH c
MATCH (owner:Person {id: $owner_id})
MERGE (owner)-[:MADE]->(c);

WITH c
OPTIONAL MATCH (proj:Project {id: $project_id})
FOREACH (_ IN CASE WHEN proj IS NULL THEN [] ELSE [1] END |
  MERGE (c)-[:RELATES_TO]->(proj)
);

OPTIONAL MATCH (cont:Contract {id: $contract_id})
FOREACH (_ IN CASE WHEN cont IS NULL THEN [] ELSE [1] END |
  MERGE (c)-[:RELATES_TO]->(cont)
);
o	Use apoc.merge.node / apoc.merge.relationship with labels/types supplied from YAML definitions.
o	All merges are parameterised (ids/properties as parameters; labels/types as config inputs) to avoid string interpolation of values.
•	Example generic upsert:
WITH $node AS node
CALL apoc.merge.node(node.labels, {id: node.id}, node.properties, {updated_at: datetime(), last_seen_at: datetime()})
YIELD node AS n
SET n.created_by = coalesce(n.created_by, $user_id),
    n.created_at = coalesce(n.created_at, datetime())
RETURN n;
•	Relationships use the same pattern with apoc.merge.relationship and optional properties from schema metadata.
3.4 Forms / Concepts / Particulars alignment
•	Every node type declares whether it is a Form (abstract), Concept (taxonomy), or Particular (instance).
•	New types must either:
o	Point to a Form category (form: "Stakeholder", "Interaction", etc.), or
o	Declare themselves as Form/Concept kinds in the YAML metadata.
•	INSTANCE_OF links are created dynamically when Particulars reference Concepts; new Particular types can target any Concept defined in the knowledgebase.
•	Forms/Concepts/Particulars co-exist: e.g. a newly added Particular label “VendorConsortium” can INSTANCE_OF a Concept “SupplierConsortium”, which in turn INSTANCE_OF the Form “Stakeholder”.
3.5 Global property conventions
All node types inherit the provenance and stability rules:
•	id (string, unique per primary label).
•	created_at, updated_at, first_seen_at, last_seen_at (ISO 8601).
•	source_uri, created_by, updated_by.
Relationship properties (if defined) may also carry created_at, updated_at, source_uri, and domain-specific attributes. IDs remain stable and MERGE is always on id + primary labels.
3.6 Seed definitions for Stakeholder Engagement (illustrative, not fixed)
•	The default knowledgebase ships with seed node/relationship definitions aligned to the stakeholder_engagement domain. They are examples, not hard-coded limits.
•	Common node seeds include Person, Org, Project, ProjectComponent, Contract, Interaction, Commitment, Issue, Risk, Outcome, Topic, Document, Policy, Agent, and StakeholderRole.
•	Common relationship seeds include WORKS_FOR, INVOLVED_IN, PARTY_TO, PARTICIPATED_IN, REPRESENTED_IN, HAS_SOURCE, MENTIONS, MADE, REQUESTED, RELATES_TO, RAISED_IN, IDENTIFIED_IN, RESULTS_IN, ASSOCIATED_WITH, INFLUENCES, ASSISTS, INSTANCE_OF, PARENT_OF, and APPLIES_TO.
•	Each seed entry in YAML includes property expectations and metadata (introduction_version, usage_frequency, deprecated flag). Pipelines should always consult the active YAML instead of assuming this list.
________________________________________
4. Node and Relationship Templates (dynamic)
Node and relationship definitions are templates driven by YAML. Code should treat them as contracts that can change:
•	Node templates
o	fields: id, labels, form/category, properties (name, datatype hint, required, defaults), metadata (introduction_version, usage_frequency, deprecated, last_seen_at).
o	Indexes/constraints are derived from templates (unique on id per label; optional secondary indexes declared in YAML).
•	Relationship templates
o	fields: id, type, from_labels, to_labels, properties, metadata (same structure as nodes).
o	Cardinality hints are descriptive only; enforcement is via validation rules in the knowledgebase.
Seed examples (subject to change by knowledgebase edits):
•	Person: id, name, email, phone, title, type, influence_score, notes + provenance fields.
•	Org: id, name, legal_name, domain, sector, type, region/country + provenance fields.
•	Interaction: id, type, subject, summary, at, location, sentiment_score, sentiment_label, source_uri, processing_version + provenance.
•	Commitment: id, text, due_date, status, priority, owner_person_id, requester hints, risk_score + provenance.
•	Relationship WORKS_FOR: (:Person)-[:WORKS_FOR {start_date, end_date}]->(:Org)
•	Relationship MENTIONS: (:Interaction)-[:MENTIONS {confidence, span}]->(Any entity label defined in YAML)
The same pattern applies to any new node/relationship type that is added by users or agents at runtime.
________________________________________
5. Schema Governance, Scoring, and Deprecation
5.1 Usage scoring
•	LOGOS tracks writes/reads per node/relationship type (usage_frequency) and decay-adjusted recency scores.
•	Scores influence:
o	Prompt weighting (high-usage concepts are prioritised).
o	Deprecation candidates (low or zero usage over a window).
o	Schema surfacing in UI (ordering, recommendations).
5.2 Deprecation flow
•	A type marked deprecated:true remains readable; new writes are blocked or redirected to successor types.
•	Deprecations are logged with when/by whom and can be undone by editing YAML.
•	Schema migrations can alias deprecated labels/relationship types to replacements while preserving ids.
5.3 Versioning and change log
•	Each schema file carries introduction_version and an appended change log entry when modified.
•	Pipelines record the schema version used in processing bundles so later replays are reproducible.
________________________________________
6. Meta-schema and diagrams
•	The ERD is now extensible: prior tables showing fixed labels are illustrative only.
•	Meta-schema view:
o	(:SchemaNodeType {id, labels, metadata})-[:ALLOWS_PROPERTY]->(:SchemaProperty {name, required, datatype_hint})
o	(:SchemaRelType {id, type, metadata})-[:FROM_LABEL]->(:SchemaLabel)-[:TO_LABEL]->(:SchemaLabel)
o	(:SchemaNodeType)-[:INSTANCE_OF]->(:Concept) to keep the Forms/Concepts/Particulars structure visible.
•	Visual diagrams should depict this meta-schema with dynamic extensions rather than enumerating every label or relationship.
________________________________________
7. Example dynamic Cypher snippets
7.1 Dynamic node upsert (any label)
WITH $schema_node AS schema_node, $payload AS payload
CALL apoc.merge.node(schema_node.labels, {id: payload.id}, payload.properties, {updated_at: datetime(), last_seen_at: datetime()})
YIELD node AS n
SET n.created_at = coalesce(n.created_at, datetime()),
    n.first_seen_at = coalesce(n.first_seen_at, datetime()),
    n.created_by = coalesce(n.created_by, $user_id),
    n.updated_by = $user_id,
    n.source_uri = payload.source_uri,
    n.metadata_version = schema_node.metadata.introduction_version;
RETURN n;
7.2 Dynamic relationship upsert (any type)
WITH $from AS fromNode, $to AS toNode, $schema_rel AS schema_rel, $rel_props AS rel_props
CALL apoc.merge.node(fromNode.labels, {id: fromNode.id}, {}, {}) YIELD node AS from_n
CALL apoc.merge.node(toNode.labels, {id: toNode.id}, {}, {}) YIELD node AS to_n
CALL apoc.merge.relationship(from_n, schema_rel.type, {}, rel_props, to_n)
YIELD rel
SET rel.created_at = coalesce(rel.created_at, datetime()),
    rel.updated_at = datetime(),
    rel.source_uri = rel_props.source_uri,
    rel.metadata_version = schema_rel.metadata.introduction_version;
RETURN rel;
These snippets illustrate the generic merge strategy; actual pipelines populate schema_node/schema_rel from knowledgebase YAML and ensure all values are passed as parameters.
