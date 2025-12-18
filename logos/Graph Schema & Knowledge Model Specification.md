Graph Schema & Knowledge Model Specification
Product: LOGOS – Cognitive Engine + Stakeholder Engagement MVP
________________________________________
1. Introduction
1.1 Purpose
This document specifies the graph schema and knowledge model for LOGOS, covering:
•	How the Platonic / Socratic concepts (Forms, Concepts, Particulars, Agents, Dialectical Lines) are represented in Neo4j.
•	The canonical set of node labels, relationship types, and properties.
•	How universal stakeholder concepts (stakeholder, relationship, issue, engagement action, risk, outcome, document, project component) map into the graph.
•	Conventions for IDs, provenance, timestamps, scores, and schema evolution.
This is the reference for any component that reads or writes to the LOGOS graph.
1.2 Scope
•	Logical and physical graph schema for Neo4j.
•	Knowledge model conventions (Forms / Concepts / Particulars / Agents).
•	Initial schema for the Stakeholder Engagement MVP, designed to be reusable for future modules (contracts, ESG, governance, etc.).
Out of scope: low-level Neo4j deployment details (covered in SAD / runbook).
1.3 Design Principles
•	Universal but extensible: schema works across industries with domain-specific extensions via Concepts and Topics.
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
3. Neo4j Schema Overview
3.1 Node Labels (Particulars + Concepts)
Core domain labels:
•	:Person
•	:Org
•	:Project
•	:ProjectComponent
•	:Contract
•	:Interaction
•	:Commitment
•	:Issue
•	:Risk
•	:Outcome
•	:Topic
•	:Document
•	:Policy
•	:Agent
•	:StakeholderRole (optional as node; can be flattened into relationship properties)
•	:Concept (taxonomy / ontology nodes, including Forms and domain concepts)
•	Optional future: :Score, :Metric if you decide to materialise metrics as nodes.
3.2 Relationship Types (Dialectical Lines + Structure)
Core relationship types (direction given from left to right):
•	Structural / organisational:
o	(:Person)-[:WORKS_FOR]->(:Org)
o	(:Org)-[:PARENT_OF]->(:Org)
•	Project & contract involvement:
o	(:Person)-[:INVOLVED_IN]->(:Project)
o	(:Org)-[:INVOLVED_IN]->(:Project)
o	(:Org)-[:PARTY_TO]->(:Contract)
o	(:Contract)-[:ASSOCIATED_WITH]->(:Project)
•	Interactions:
o	(:Person)-[:PARTICIPATED_IN]->(:Interaction)
o	(:Org)-[:REPRESENTED_IN]->(:Interaction)
o	(:Interaction)-[:HAS_SOURCE]->(:Document)
•	Content / mentions:
o	(:Interaction)-[:MENTIONS]->(:Topic|:Org|:Person|:Project|:Contract|:Issue|:Risk)
o	(:Issue)-[:TAGGED_AS]->(:Topic)
o	(:Commitment)-[:TAGGED_AS]->(:Topic)
•	Commitments & actions:
o	(:Person)-[:MADE]->(:Commitment) // Usually the internal owner
o	(:Person)-[:REQUESTED]->(:Commitment) // Who asked for it (if person)
o	(:Org)-[:REQUESTED]->(:Commitment) // Who asked for it (if org)
o	(:Commitment)-[:RELATES_TO]->(:Project|:Contract|:Topic|:Issue|:ProjectComponent)
•	Issues, risks, outcomes:
o	(:Issue)-[:RAISED_IN]->(:Interaction)
o	(:Risk)-[:IDENTIFIED_IN]->(:Interaction)
o	(:Issue)-[:RELATED_TO]->(:Risk)
o	(:Risk)-[:RESULTS_IN]->(:Outcome)
o	(:Outcome)-[:ASSOCIATED_WITH]->(:Project|:ProjectComponent)
•	Stakeholder roles:
o	(:StakeholderRole)-[:FOR_PERSON]->(:Person) (optional)
o	(:StakeholderRole)-[:FOR_ORG]->(:Org) (optional)
o	(:StakeholderRole)-[:IN_PROJECT]->(:Project) or [:IN_CONTRACT]->(:Contract)
•	Influence / reasoning:
o	(:Person)-[:INFLUENCES {weight}]->(:Person)
o	(:Org)-[:INFLUENCES {weight}]->(:Org)
o	(:Agent)-[:ASSISTS]->(:Person)
•	Concept / type system:
o	(:Concept)-[:FORM_OF]->(:Concept) // For “Form” meta-relationships if used
o	(:Concept)-[:PARENT_OF]->(:Concept) // Concept hierarchies (e.g. Topic taxonomies)
o	(:Node)-[:INSTANCE_OF]->(:Concept) // Where :Node is any domain node label
You are free to collapse :StakeholderRole into relationship properties if you prefer a leaner graph; this spec keeps it explicit but optional.
3.3 Global Property Conventions
All “main” nodes (:Person, :Org, :Project, :Contract, :Commitment, etc.) share:
•	id (string, globally unique within that label; e.g. p_<hash>, o_<hash>, pr_<hash>)
•	created_at (datetime string; ISO 8601)
•	updated_at (datetime string)
•	first_seen_at (datetime when first observed)
•	last_seen_at (datetime when last confirmed by processing)
•	source_uri (string; original data source identifier)
•	created_by (string; user or system identifier)
•	updated_by (string; user or system identifier)
Relationships may include:
•	created_at
•	updated_at
•	source_uri
•	Domain-specific attributes (e.g. weight on :INFLUENCES).
3.4 IDs and Idempotency
•	IDs should be stable, not Neo4j internal IDs.
•	Recommended approach:
o	Deterministic IDs based on source system + intrinsic keys (e.g. hashed email, external project code), or
o	Synthetic IDs generated and stored in LOGOS (prefix + UUID/hash).
•	All upserts use MERGE on id to guarantee idempotency.
________________________________________
4. Node Specifications
For each label:
•	Purpose.
•	Core properties.
•	Recommended indexes/constraints.
•	Notes.
4.1 :Person
Purpose: Represents individual stakeholders (internal or external).
Properties:
•	id (string, PK)
•	name (string)
•	email (string, optional)
•	phone (string, optional)
•	title (string, job title)
•	type (string; internal, external, consultant, community_rep, regulator, etc.)
•	influence_score (float; derived)
•	notes (string, optional)
•	Global provenance fields: source_uri, created_at, updated_at, first_seen_at, last_seen_at, created_by, updated_by
Indexes / Constraints:
•	CONSTRAINT person_id_unique IF NOT EXISTS ON (p:Person) ASSERT p.id IS UNIQUE;
•	Optional index on :Person(email).
________________________________________
4.2 :Org
Purpose: Represents organisations (suppliers, regulators, community groups, internal business units).
Properties:
•	id (string, PK)
•	name (string)
•	legal_name (string, optional)
•	domain (string; e.g. acme.com)
•	sector (string; mining, energy, etc.)
•	type (string; supplier, regulator, community, internal, etc.)
•	country, region (strings, optional)
•	Global provenance fields.
Indexes / Constraints:
•	CONSTRAINT org_id_unique IF NOT EXISTS ON (o:Org) ASSERT o.id IS UNIQUE;
•	Index on :Org(name) and :Org(domain) recommended.
________________________________________
4.3 :Project
Purpose: Represents projects / initiatives LOGOS tracks.
Properties:
•	id (string, PK)
•	name (string)
•	code (string, optional)
•	status (string; planned, active, paused, closed)
•	description (string, optional)
•	start_date, end_date (date strings, optional)
•	sponsor_person_id (string, optional for quick linking)
•	Global provenance fields.
Indexes / Constraints:
•	CONSTRAINT project_id_unique IF NOT EXISTS ON (p:Project) ASSERT p.id IS UNIQUE;
•	Index on :Project(code) and :Project(name) if needed.
________________________________________
4.4 :ProjectComponent
Purpose: Represents scope items, work packages, assets, or logical components of a project.
Properties:
•	id (string, PK)
•	name
•	type (string; work_package, milestone, asset, stakeholder_cluster, etc.)
•	status (string)
•	description (string, optional)
•	Global provenance fields.
Indexes / Constraints:
•	Unique on id.
________________________________________
4.5 :Contract
Purpose: Represents a contract or agreement.
Properties:
•	id (string, PK)
•	sap_id or external ID (string, optional)
•	name
•	value (float, optional)
•	currency (string, optional)
•	start_date, end_date (date strings)
•	status (string)
•	description (string, optional)
•	Global provenance fields.
Indexes / Constraints:
•	Unique on id.
•	Optional index on sap_id.
________________________________________
4.6 :Interaction
Purpose: Represents a discrete interaction (meeting, call, email, workshop, note).
Properties:
•	id (string, PK)
•	type (string; meeting, call, email, note, workshop, site_visit)
•	subject (string, optional)
•	summary (string; AI or human-generated)
•	at (datetime string)
•	location (string, optional)
•	sentiment_score (float; -1 to 1)
•	sentiment_label (string; negative, neutral, positive)
•	source_uri (string; path, email ID, etc.)
•	processing_version (string; model version used)
•	Global provenance fields.
Indexes / Constraints:
•	Unique on id.
•	Index on at for timeline queries.
________________________________________
4.7 :Commitment
Purpose: Represents a commitment or engagement action arising from an Interaction.
Properties:
•	id (string, PK)
•	text (string; obligation/action description)
•	due_date (date string, optional)
•	status (string; proposed, accepted, in_progress, done, cancelled)
•	priority (string; low, medium, high, critical)
•	owner_person_id (string, optional; convenience for quick access)
•	risk_score (float, optional; derived)
•	age_days (int, optional; derived)
•	Global provenance fields.
Indexes / Constraints:
•	Unique on id.
•	Index on status and due_date for alert queries.
________________________________________
4.8 :Issue
Purpose: Represents an issue or concern raised in interactions.
Properties:
•	id (string, PK)
•	title
•	description
•	category (string; aligned to Topic taxonomy)
•	status (string; open, monitoring, mitigated, closed)
•	severity (string; low, medium, high, critical)
•	Global provenance fields.
Indexes / Constraints:
•	Unique on id.
________________________________________
4.9 :Risk
Purpose: Represents a risk related to stakeholders, projects, or outcomes.
Properties:
•	id (string, PK)
•	title
•	description
•	category (string; commercial, safety, schedule, reputation, ESG, etc.)
•	likelihood (numeric or coded string)
•	impact (numeric or coded string)
•	score (float; derived from likelihood × impact or model)
•	status (string; identified, assessed, mitigated, closed)
•	Global provenance fields.
Indexes / Constraints:
•	Unique on id.
________________________________________
4.10 :Outcome
Purpose: Represents realised outcomes (positive or negative) linked to projects/stakeholders.
Properties:
•	id (string, PK)
•	title
•	description
•	type (string; success, failure, partial, community_impact, regulatory_outcome, etc.)
•	realised_date (date string)
•	Global provenance fields.
Indexes / Constraints:
•	Unique on id.
________________________________________
4.11 :Topic
Purpose: Represents topics/tags used to classify interactions, commitments, issues, risks, etc.
Properties:
•	id (string, PK)
•	name
•	category (string; domain-specific)
•	description (string, optional)
•	slug (string; URL-safe/identifier)
•	Global provenance fields.
Indexes / Constraints:
•	Unique on id.
•	Index on name.
________________________________________
4.12 :Document
Purpose: Represents a source document input to LOGOS.
Properties:
•	id (string, PK)
•	file_name (string)
•	uri (string; absolute path or storage URI)
•	mime_type (string)
•	hash (string; content hash for deduplication)
•	ingested_at (datetime)
•	Global provenance fields.
Indexes / Constraints:
•	Unique on id.
•	Optional unique on hash.
________________________________________
4.13 :Policy
Purpose: Represents internal policies or governance documents.
Properties:
•	id (string, PK)
•	name
•	description
•	category
•	effective_from, effective_to (date strings, optional)
•	Global provenance fields.
Indexes / Constraints:
•	Unique on id.
________________________________________
4.14 :Agent
Purpose: Represents an AI agent instance configured for a user or team.
Properties:
•	id (string, PK)
•	name
•	description
•	profile (map / JSON-encoded string; e.g. preferences, prompt set)
•	domain_profile (string; e.g. stakeholder_engagement)
•	Global provenance fields.
Indexes / Constraints:
•	Unique on id.
________________________________________
4.15 :StakeholderRole (optional node)
Purpose: Explicitly captures role context (who plays what role in which project/contract).
Properties:
•	id (string, PK)
•	role_type (string; decision_maker, influencer, end_user, regulator, community_rep, internal_sponsor, etc.)
•	is_primary (boolean)
•	notes (string, optional)
•	Global provenance fields.
Indexes / Constraints:
•	Unique on id.
Alternative: represent roles directly on relationships with properties:
•	(:Person)-[:INVOLVED_IN {role_type: "decision_maker", is_primary: true}]->(:Project)
Choose one pattern and stick to it. For MVP, relationship properties are simpler; node form is more flexible for complex analysis.
________________________________________
4.16 :Concept
Purpose: Represents Forms and domain-specific concepts (StakeholderType, RiskCategory, OutcomeType, etc.).
Properties:
•	id (string, PK)
•	name
•	kind (string; Form, StakeholderType, RiskCategory, IssueCategory, OutcomeType, PolicyCategory, TopicGroup, etc.)
•	description (string, optional)
•	metadata (map / JSON-encoded; arbitrary extra config)
•	Global provenance fields.
Indexes / Constraints:
•	Unique on id.
•	Index on kind.
________________________________________
5. Relationship Specifications
Below are key relationships with purpose, direction, and main properties.
5.1 WORKS_FOR
•	Pattern: (:Person)-[:WORKS_FOR]->(:Org)
•	Purpose: Employment / affiliation.
•	Properties:
o	start_date, end_date (optional)
•	Cardinality:
o	Person → 0..N Orgs (multi-affiliation allowed if needed).
o	Org → 0..N Persons.
________________________________________
5.2 PARENT_OF (Org hierarchy)
•	Pattern: (:Org)-[:PARENT_OF]->(:Org)
•	Purpose: Represent parent/child organisation structure.
•	Properties: none currently; just hierarchy.
•	Cardinality:
o	Org → 0..N child Orgs.
•	Note: can be extended into general corporate tree.
________________________________________
5.3 INVOLVED_IN (Person/Org ↔ Project)
•	Patterns:
o	(:Person)-[:INVOLVED_IN {role_type, is_primary}]->(:Project)
o	(:Org)-[:INVOLVED_IN {role_type, is_primary}]->(:Project)
•	Purpose: Project involvement roles.
•	Properties:
o	role_type, is_primary, start_date, end_date.
•	Cardinality: many-to-many.
________________________________________
5.4 PARTY_TO (Org ↔ Contract)
•	Pattern: (:Org)-[:PARTY_TO {role}]->(:Contract)
•	Purpose: Link organisations to contracts.
•	Properties:
o	role (e.g. principal, contractor, subcontractor).
________________________________________
5.5 PARTICIPATED_IN / REPRESENTED_IN (Interaction)
•	Patterns:
o	(:Person)-[:PARTICIPATED_IN {role}]->(:Interaction)
o	(:Org)-[:REPRESENTED_IN]->(:Interaction)
•	Purpose: Who attended or took part in an interaction.
•	Properties:
o	role (e.g. host, participant, observer).
________________________________________
5.6 HAS_SOURCE (Interaction ↔ Document)
•	Pattern: (:Interaction)-[:HAS_SOURCE]->(:Document)
•	Purpose: Link interactions to underlying documents (emails, minutes, transcripts).
________________________________________
5.7 MENTIONS
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
