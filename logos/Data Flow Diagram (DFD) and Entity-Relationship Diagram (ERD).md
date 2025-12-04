Data Flow Diagram (DFD) and Entity-Relationship Diagram (ERD)
Product: LOGOS – Cognitive Engine + Stakeholder Engagement MVP
________________________________________
1. Introduction
1.1 Purpose
This document describes the logical data flows and the data model for LOGOS, including:
•	The ingestion and enrichment pipeline (documents/audio → structured graph).
•	The query and reasoning pipeline (search, stakeholder views, alerts).
•	The core entities and relationships, aligned with:
o	Universal stakeholder model (stakeholder, relationship, issue, engagement action, risk, outcome).
o	The Platonic/Socratic LOGOS Core (Forms, Concepts, Particulars, Agents).
o	The Neo4j graph schema used in implementation.
You can use this as the basis for drawing formal DFD and ERD diagrams.
1.2 Scope
•	Logical DFDs:
o	Level 0 context.
o	Level 1 for ingestion/enrichment.
o	Level 1 for query/reasoning.
•	ERD:
o	Core entities, attributes, and relationships.
o	Mapping to the Neo4j node/relationship model.
________________________________________
2. Data Flow Diagrams (DFDs)
2.1 Level 0 – Context Diagram
System: LOGOS (Core + Stakeholder Engagement MVP)
External Entities:
1.	Business User
o	Category Manager, Project Lead, Analyst, Exec.
2.	Local File System / Document Sources
o	Network drives, SharePoint exports, manual uploads.
3.	Local AI Services (optional)
o	Local LLM host (e.g. Ollama).
o	Local ASR.
o	Local OCR.
4.	Graph Store
o	Neo4j database instance (treated as an external data store for context).
Main Process:
•	P0 – LOGOS Core & Stakeholder Engagement
Data Stores (logical):
•	D1 – Knowledgebase & Config
o	Prompts, patterns, ontologies, model configs, thresholds.
•	D2 – Processing Staging
o	Temporary storage for uploaded files and preview bundles.
•	D3 – Knowledge Graph (Neo4j)
o	Persons, Orgs, Projects, Commitments, Interactions, Issues, Risks, etc.
Key Data Flows:
•	Business User → P0:
o	Uploaded documents / audio.
o	Text notes.
o	Queries (search, stakeholder lookup).
o	Edits to extracted data (preview).
o	Status updates (commitments, issues).
•	P0 → Business User:
o	Previews of extracted entities/relationships.
o	Stakeholder 360 views.
o	Search results and graph views.
o	Alerts and risk signals.
o	Summaries and reports (if/when agent views are exposed).
•	P0 ↔ Local AI Services:
o	Requests for extraction, summarisation, classification.
o	Responses with structured JSON or text.
•	P0 ↔ D1 (Knowledgebase):
o	Loading/saving prompts, configs, ontologies.
•	P0 ↔ D3 (Neo4j):
o	Graph reads and writes (upsert, queries).
________________________________________
2.2 Level 1 – Ingestion & Enrichment Pipeline
Process Group: P1 – Ingest & Enrich
Sub-processes:
•	P1.1 – Document / Audio Ingestion
•	P1.2 – Text Extraction & Transcription
•	P1.3 – NLP Extraction (Entities, Relationships, Commitments)
•	P1.4 – Normalisation & Entity Resolution
•	P1.5 – Preview Bundle Assembly
•	P1.6 – Graph Upsert & Provenance
•	P1.7 – Alert Evaluation
Data Stores:
•	D2 – Processing Staging
•	D3 – Knowledge Graph (Neo4j)
•	D1 – Knowledgebase & Config
P1.1 – Document / Audio Ingestion
Inputs:
•	From Business User:
o	File upload (DOCX/PDF/TXT/CSV).
o	Audio upload (WAV/MP3).
o	Free-text notes.
Process:
•	Validate file type and size.
•	Store raw file temporarily in D2.
•	Create a provisional Interaction record in D2 with:
o	interaction_id.
o	metadata (user, timestamp, source_uri, file type).
Outputs:
•	To P1.2:
o	File handle / raw content reference.
o	Interaction metadata.
P1.2 – Text Extraction & Transcription
Inputs:
•	Raw file/audio from P1.1.
Process:
•	If document:
o	Parse to text + simple structure (headings, paragraphs, tables where possible).
•	If audio:
o	Call ASR (local) to generate transcript text.
•	Optionally run OCR for scanned PDFs via local OCR service.
Outputs:
•	To P1.3:
o	text (plain text or lightly structured).
o	Extended metadata:
	Document date (if detectable).
	File name and path.
	Interaction type (meeting, call, note) if known.
P1.3 – NLP Extraction
Inputs:
•	Text + metadata from P1.2.
•	Knowledgebase patterns and prompts from D1.
Process:
•	Run NER and relation extraction.
•	Identify entities:
o	Persons, Organisations, Projects, Contracts, Topics, Issues, Risks, Outcomes, Documents, Policies.
•	Identify Stakeholder roles:
o	Classify Persons/Orgs as internal vs external; role (supplier, regulator, community, partner, internal team).
•	Extract Commitments (primary engagement actions for MVP):
o	Obligation text.
o	Due dates (resolved from relative references, e.g. “next week”).
o	Owner (internal Person).
o	Requester (external stakeholder or internal).
•	Extract Issues/Concerns:
o	Issue descriptions and categories.
•	Extract Sentiment:
o	Interaction-level sentiment score and label.
•	Extract Topics:
o	Tags and key phrases.
Outputs:
•	To P1.4:
o	Extraction bundle:
	entities, relationships, metrics.
P1.4 – Normalisation & Entity Resolution
Inputs:
•	Extraction bundle from P1.3.
•	Candidate entity lists from D3 (via GraphIO).
Process:
•	Match to existing Persons/Orgs/Projects/Contracts:
o	Exact ID/email/domain matches.
o	Fuzzy name/org matches.
•	Decide:
o	New vs existing entity.
•	Compute confidence scores for matches.
Outputs:
•	To P1.5:
o	Resolved extraction bundle:
	Entities with canonical IDs or marked as new.
	Relationships pointing to canonical IDs.
	Confidence flags.
P1.5 – Preview Bundle Assembly
Inputs:
•	Resolved extraction bundle from P1.4.
•	Interaction metadata from P1.1/1.2.
Process:
•	Wrap bundle into a preview object:
o	Proposed Interaction node (with text summary, sentiment).
o	Proposed Persons/Orgs/Projects/Commitments/Issues etc.
o	Proposed relationships.
o	Confidence scores and flags for user review.
•	Persist preview in D2 keyed by interaction_id.
Outputs:
•	To Business User (via UI): preview data for review and correction.
•	To P1.6 when user confirms.
P1.6 – Graph Upsert & Provenance
Inputs:
•	User-confirmed preview bundle from UI.
•	Graph schema/config from D1.
Process:
•	Construct graph upsert operations:
o	MERGE nodes for Persons, Orgs, Projects, Contracts, Topics, Commitments, Interactions, Issues, Risks, Outcomes, Documents.
o	MERGE relationships: WORKS_FOR, INVOLVED_IN, PARTY_TO, MENTIONS, MADE, RELATES_TO, INFLUENCES, etc.
•	Attach provenance and timestamps:
o	source_uri, first_seen_at, last_seen_at, created_by, updated_by.
Outputs:
•	To D3 (Neo4j):
o	Transactional graph upserts.
•	To P1.7:
o	interaction_id and updated node/relationship references.
P1.7 – Alert Evaluation
Inputs:
•	Newly committed Interaction and related nodes from P1.6.
•	Alert rules and thresholds from D1.
Process:
•	Recalculate risk/alert state for:
o	Affected stakeholders (Persons/Orgs).
o	Affected projects.
o	Relevant commitments.
•	Examples:
o	Unresolved commitments past due.
o	Sentiment drop over last N interactions.
Outputs:
•	To D3 (Neo4j) and/or dedicated alert store:
o	Alert nodes/relationships or flags.
•	To Business User:
o	Updated alerts listing via /alerts.
________________________________________
2.3 Level 1 – Query & Reasoning Pipeline
Process Group: P2 – Query, Reasoning & Reporting
Sub-processes:
•	P2.1 – Search & Discovery
•	P2.2 – Stakeholder 360 View
•	P2.3 – Project Map & Graph Views
•	P2.4 – Alerts & Risk Overview
•	P2.5 – Agent-Assisted Queries & Summaries (optional in MVP)
P2.1 – Search & Discovery
Inputs:
•	Query text from Business User (q=...).
•	Filters (type: stakeholder, project, commitment; date ranges).
Process:
•	Full-text search over names, descriptions, topics.
•	Graph-index search over node properties.
•	Optional semantic search if vector index is enabled.
Outputs:
•	Lists of matching entities (Persons, Orgs, Projects, Commitments, Issues, Documents, Interactions).
•	Quick context snippets (e.g. last interaction date, sentiment).
P2.2 – Stakeholder 360 View
Inputs:
•	Selected stakeholder ID (Person or Org).
Process:
•	Query D3 for:
o	Stakeholder profile (attributes, roles).
o	Interactions timeline.
o	Open and closed commitments.
o	Linked projects/contracts/issues.
o	Sentiment trend.
o	Alerts/risk flags.
•	Reasoning:
o	Compute stakeholder risk score.
o	Compute influence metrics (e.g. centrality, influence edges).
Outputs:
•	To Business User:
o	360-degree view: tables + charts + simple graph.
P2.3 – Project Map & Graph Views
Inputs:
•	Project ID (or project search).
Process:
•	Query D3 for:
o	Linked stakeholders (Persons, Orgs, stakeholder roles).
o	Commitments, issues, risks.
o	Interactions associated with the project.
•	Build:
o	Ego network around project node.
o	Optional path analysis (e.g. from key stakeholders to critical outcomes).
Outputs:
•	Project-centric graph view and summaries.
P2.4 – Alerts & Risk Overview
Inputs:
•	Request to /alerts or risk dashboard.
Process:
•	Query D3 for:
o	Active alerts (unresolved commitments, sentiment drops, etc.).
o	Aggregated risk scores by stakeholder/org/project.
Outputs:
•	Alert list with filters (owner, stakeholder, project).
•	Risk overview by dimension (e.g. top 10 at-risk stakeholders).
P2.5 – Agent-Assisted Queries & Summaries (future-facing)
Inputs:
•	Natural language question from Business User.
Process:
•	Agent Service:
o	Parses intent and selects pipeline(s).
o	Runs graph queries (search, reasoning).
o	Optionally calls local LLM with prompts and context from D3 and D1.
Outputs:
•	Human-readable answer plus links to underlying objects (stakeholders, interactions, commitments, issues, risks, outcomes).
________________________________________
3. Entity-Relationship Diagram (ERD) – Logical Data Model
Note: Implementation uses Neo4j (graph), but this section describes the entities and relationships in ERD terms (entities, attributes, cardinalities). Mapping to graph labels/relationships is straightforward.
3.1 Core Universal Concepts
The data model must support the universal core:
•	Stakeholder (Person or Organisation, with roles and classifications).
•	Relationship / Influence / Sentiment (between stakeholders and with the organisation).
•	Issue / Concern.
•	Engagement Action (meetings, commitments, communications).
•	Project Component / Scope Item.
•	Document / Meeting / Correspondence.
•	Risk.
•	Outcome.
These are implemented via the entities below.
________________________________________
3.2 Entities and Attributes
For brevity, types are indicative (string, int, date, float, bool, JSON).
3.2.1 Person
Represents an individual stakeholder (internal or external).
•	person_id (PK)
•	name
•	email
•	phone
•	title (job title/role)
•	org_id (FK → Organisation)
•	type (internal, external, consultant, community_rep, regulator, etc.)
•	influence_score (derived numeric; optional)
•	notes (free text)
•	created_at, updated_at
•	source_uri (provenance)
3.2.2 Organisation
Represents an organisation (supplier, regulator, community group, etc.).
•	org_id (PK)
•	name
•	legal_name
•	domain (e.g. acme.com)
•	sector (mining, energy, construction, government, etc.)
•	type (supplier, regulator, JV_partner, community, internal_business_unit, etc.)
•	country, region
•	parent_org_id (FK self-reference, optional)
•	created_at, updated_at
•	source_uri
3.2.3 StakeholderRole
Classifies a Person/Organisation in relation to a Project/Contract or the organisation.
•	stakeholder_role_id (PK)
•	person_id (FK → Person, nullable)
•	org_id (FK → Organisation, nullable)
•	project_id (FK → Project, nullable)
•	contract_id (FK → Contract, nullable)
•	role_type (e.g. decision_maker, influencer, end_user, regulator, community_rep, internal_sponsor)
•	is_primary (bool)
•	notes
•	created_at, updated_at
3.2.4 Project
Represents a project or initiative.
•	project_id (PK)
•	name
•	code
•	status (planned, active, paused, closed)
•	description
•	start_date, end_date (planned/actual)
•	sponsor_person_id (FK → Person, optional)
•	created_at, updated_at
•	source_uri
3.2.5 ProjectComponent
Represents a scope item or component within a project (for fine-grained mapping).
•	component_id (PK)
•	project_id (FK → Project)
•	name
•	description
•	type (e.g. work_package, milestone, asset, stakeholder_cluster)
•	status
•	parent_component_id (FK self-reference, optional)
•	created_at, updated_at
3.2.6 Contract
Represents a commercial/legal agreement.
•	contract_id (PK)
•	sap_id or external ID
•	name
•	value (numeric, use value + currency)
•	currency
•	start_date, end_date
•	status
•	description
•	project_id (FK → Project, optional)
•	created_at, updated_at
•	source_uri
3.2.7 Topic
Represents a topic/issue label used to tag interactions, commitments, and risks.
•	topic_id (PK)
•	name
•	category (e.g. safety, schedule, community, environment, commercial)
•	description
•	parent_topic_id (FK self-reference, optional)
•	created_at, updated_at
3.2.8 Interaction
Represents a discrete interaction: meeting, call, email, workshop, site visit, etc.
•	interaction_id (PK)
•	type (meeting, call, email, note, workshop, site_visit)
•	subject / title
•	summary (auto or human-generated)
•	at (datetime of interaction)
•	location
•	source_uri (file path, email ID, etc.)
•	sentiment_score (float, -1 to 1)
•	sentiment_label (negative/neutral/positive)
•	created_by_person_id (FK → Person, internal owner)
•	created_at, updated_at
3.2.9 Commitment (Engagement Action – MVP focus)
Represents a commitment or action arising from an interaction.
•	commitment_id (PK)
•	interaction_id (FK → Interaction)
•	text (description of commitment/action)
•	due_date (date; may be null if unspecified)
•	status (proposed, accepted, in_progress, done, cancelled)
•	priority (low/medium/high/critical)
•	owner_person_id (FK → Person – internal owner)
•	requester_person_id (FK → Person – who requested; nullable)
•	requester_org_id (FK → Organisation – external counterparty; nullable)
•	project_id (FK → Project, nullable)
•	component_id (FK → ProjectComponent, nullable)
•	contract_id (FK → Contract, nullable)
•	created_at, updated_at
•	source_uri
Note: Other engagement actions (e.g. outreach events, comms campaigns) can later be modelled either as additional Commitment types or a separate EngagementAction entity referencing Interaction/Project/Stakeholder.
3.2.10 Issue
Represents an issue or concern raised.
•	issue_id (PK)
•	interaction_id (FK → Interaction, original context)
•	title
•	description
•	category (aligned with Topic categories)
•	status (open, monitoring, mitigated, closed)
•	severity (low/medium/high/critical)
•	project_id (FK → Project, nullable)
•	component_id (FK → ProjectComponent, nullable)
•	created_at, updated_at
•	source_uri
3.2.11 Risk
Represents a risk related to stakeholders, projects, or outcomes.
•	risk_id (PK)
•	title
•	description
•	category (commercial, safety, schedule, reputation, ESG, etc.)
•	likelihood (scale or code)
•	impact (scale or code)
•	score (numeric; e.g. likelihood × impact)
•	status (identified, assessed, mitigated, closed)
•	project_id (FK → Project, nullable)
•	component_id (FK → ProjectComponent, nullable)
•	created_at, updated_at
•	source_uri
3.2.12 Outcome
Represents a realised outcome linked to stakeholders/projects (positive or negative).
•	outcome_id (PK)
•	title
•	description
•	type (success, failure, partial, community_impact, regulatory_outcome)
•	realised_date
•	project_id (FK → Project, nullable)
•	component_id (FK → ProjectComponent, nullable)
•	created_at, updated_at
•	source_uri
3.2.13 Document
Represents a source document (file) ingested by LOGOS.
•	document_id (PK)
•	file_name
•	file_path / uri
•	mime_type
•	hash (for deduplication)
•	created_at, updated_at
•	ingested_at
•	owner_person_id (FK → Person, optional)
•	project_id (FK → Project, optional)
3.2.14 Policy
Represents internal policies, standards, or governance rules.
•	policy_id (PK)
•	name
•	description
•	category
•	effective_from, effective_to
•	document_id (FK → Document, optional)
•	created_at, updated_at
3.2.15 Agent (AI Agent)
Represents an AI agent instance for a user or group.
•	agent_id (PK)
•	name
•	description
•	owner_person_id (FK → Person)
•	profile (JSON – preferences, prompt variants)
•	created_at, updated_at
________________________________________
3.3 Relationships and Cardinalities (ERD View)
Below is the ERD-style relationship set (cardinality described in prose):
1.	Person–Organisation
o	Person(org_id) → Organisation(org_id)
o	Each Person belongs to zero or one Organisation.
o	One Organisation can have many Persons.
2.	Person–Project (involvement)
o	Person ↔ Project via relationship:
	Many-to-many: a Person can be involved in many Projects; a Project can have many Persons.
o	In graph, modelled as (:Person)-[:INVOLVED_IN]->(:Project) with attributes (role, start_date, end_date).
3.	StakeholderRole
o	Links Person/Organisation to Project/Contract:
	A StakeholderRole references either a Person or an Organisation (or both, in some cases) and optionally a Project and/or Contract.
o	Represents roles like decision maker, influencer, etc.
4.	Organisation–Contract
o	Many-to-many via relationship:
	(:Org)-[:PARTY_TO]->(:Contract)
o	A Contract usually connects at least two Organisations (client and supplier).
5.	Project–Contract
o	Contract(project_id) → Project(project_id)
o	A Contract can be associated with one Project; a Project can have many Contracts.
6.	Project–ProjectComponent
o	ProjectComponent(project_id) → Project(project_id)
o	A Project can have many ProjectComponents.
7.	Interaction–Person / Interaction–Organisation
o	Many-to-many:
	(:Person)-[:PARTICIPATED_IN]->(:Interaction)
	(:Org)-[:REPRESENTED_IN]->(:Interaction) or similar.
o	An Interaction can include many Persons and Orgs; a Person/Org can appear in many Interactions.
8.	Interaction–Document
o	Optional 1-to-many:
	A Document may underlie an Interaction (e.g. an email, meeting minutes).
	In graph: (:Interaction)-[:HAS_SOURCE]->(:Document).
9.	Interaction–Topic / Issue / Risk / Project / Contract
o	Many-to-many via relationships:
	(:Interaction)-[:MENTIONS]->(:Topic|:Issue|:Risk|:Project|:Contract).
10.	Interaction–Commitment
o	Commitment(interaction_id) → Interaction(interaction_id)
o	An Interaction can have many Commitments; a Commitment belongs to one Interaction.
11.	Commitment–Person/Organisation/Project/Contract
o	Commitment.owner_person_id → Person(person_id) (internal owner).
o	Commitment.requester_person_id → Person(person_id) (person who asked for the commitment, optional).
o	Commitment.requester_org_id → Organisation(org_id) (external counterparty, optional).
o	Commitment.project_id → Project(project_id) (optional).
o	Commitment.contract_id → Contract(contract_id) (optional).
o	In graph, also:
	(:Person)-[:MADE]->(:Commitment) where direction and semantics reflect owner/requester roles.
	(:Commitment)-[:RELATES_TO]->(:Project|:Contract|:Topic|:Issue).
12.	Issue–Project / Component / Risk
o	Issue.project_id → Project(project_id).
o	Issue.component_id → ProjectComponent(component_id).
o	In graph, an Issue may also relate to Risks:
	(:Issue)-[:RELATED_TO]->(:Risk).
13.	Risk–Project / Component / Outcome
o	Risk.project_id → Project(project_id).
o	Risk.component_id → ProjectComponent(component_id).
o	(:Risk)-[:REALISES_IN]->(:Outcome) or (:Outcome)-[:RESULT_OF]->(:Risk).
14.	Outcome–Project / Component
o	Outcome.project_id → Project(project_id).
o	Outcome.component_id → ProjectComponent(component_id).
15.	Person–Person Influence
o	(:Person)-[:INFLUENCES {weight}]->(:Person)
o	Directed; can be derived from interaction patterns or manually set.
16.	Agent–Person
o	Agent.owner_person_id → Person(person_id).
o	In graph: (:Agent)-[:ASSISTS]->(:Person).
17.	Policy–Document / Project / Contract
o	Policy.document_id → Document(document_id) (policy document).
o	Optional relationships:
	(:Policy)-[:APPLIES_TO]->(:Project|:Contract).
________________________________________
3.4 Mapping ERD to Neo4j Graph
•	Each ERD entity becomes one or more labels:
o	Person → :Person
o	Organisation → :Org
o	Project → :Project
o	ProjectComponent → :ProjectComponent
o	Contract → :Contract
o	Topic → :Topic
o	Interaction → :Interaction
o	Commitment → :Commitment
o	Issue → :Issue
o	Risk → :Risk
o	Outcome → :Outcome
o	Document → :Document
o	Policy → :Policy
o	Agent → :Agent
o	StakeholderRole can be a node (:StakeholderRole) or realised as relationship properties.
•	Primary keys (*_id) are stored as id property on nodes.
•	Relationships map exactly as described in 3.3 using Neo4j relationship types.
________________________________________
3.5 Notes for Implementation
•	For MVP:
o	You can simplify by:
	Treating StakeholderRole and ProjectComponent as optional and bringing them in as needed.
	Focus on Person, Org, Project, Contract, Interaction, Commitment, Issue, Risk, Topic, Outcome.
o	Commitments act as the primary Engagement Actions; later expansions can add more action types.
•	ERD vs Graph:
o	For relational reporting, you can derive tables/views from the graph using Cypher queries or ETL into a relational store if needed.
o	The logical ERD above is intentionally close to the graph model to keep conceptual overhead low.

