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
