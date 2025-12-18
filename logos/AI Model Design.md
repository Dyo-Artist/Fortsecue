AI Model Design Document
Product: LOGOS – Cognitive Engine + Stakeholder Engagement MVP
________________________________________
1. Introduction
1.1 Purpose
This document defines the AI model design for LOGOS, covering:
•	The cognitive engine (“LOGOS Core”) that reasons over a Neo4j knowledge graph.
•	The NLP and extraction models that turn unstructured inputs into structured entities, relationships, and signals.
•	The personalised agents bound to users.
•	The scoring and alerting models for risk, sentiment, and commitments.
It focuses on how models are structured, how they interact, how they are trained, and how they are deployed within a local-first, modular system that can power multiple business applications, starting with the Stakeholder Engagement Tool (MVP 1).
1.2 Scope
This design covers:
•	Models and logic used by LOGOS Core, independent of any single UI.
•	Additional or tuned models needed for the Stakeholder Engagement MVP.
•	How models are made pluggable and reusable across domains (contracts, ESG, governance, etc.).
This is a design document, not a requirements spec; functional requirements are defined in the SRS.
1.3 Design Goals and Constraints
•	Local-first: All core models must be able to run on on-prem hardware. External APIs (e.g. cloud LLMs) are optional plug-ins, not hard dependencies.
•	Graph-centric: Neo4j is the primary store; models must integrate cleanly with graph data (nodes, relationships, properties).
•	Modular and pluggable:
o	Models are wrapped in well-defined service interfaces.
o	It must be straightforward to swap a rule-based model for an ML model (or a local LLM) without changing the rest of the pipeline.
•	Explainable where it matters:
o	Users must be able to see “why” a risk, sentiment, or alert was produced.
•	Resource aware:
o	Must run on a single machine (e.g. 16–32 GB RAM) with optional GPU acceleration.
o	Heavy models can be downgraded to lighter rule-based baselines where necessary.
________________________________________
2. Model Overview
LOGOS uses a set of model classes, each responsible for a different layer of cognition.
2.1 Core Model Classes
1.	NLP Extraction Models
o	Purpose: Convert raw text (documents, transcripts, notes) into structured objects aligned with the LOGOS schema.
o	Outputs:
	Entities: Person, Organisation, Project, Stakeholder, Interaction, Commitment, Issue, Risk, Topic, Document.
	Relationships: WORKS_FOR, PARTICIPATED_IN, MADE, RELATES_TO, MENTIONS, INFLUENCES, etc.
	Metadata: sentiment, sections, key sentences.
o	Approach:
	Rule-based patterns and regex for high-precision cues.
	Statistical or transformer-based NER / relation extraction for robustness.
	Optional wrapper around a local LLM for “few-shot” extraction tasks.
2.	Normalisation & Entity Resolution Models
o	Purpose: Map extracted surface forms (“Bob Smith”, “Robert J. Smith”, “ACME Pty”) to canonical graph entities.
o	Outputs:
	Decisions about whether an entity is new vs duplicate.
	Confidence scores to support human review when needed.
o	Approach:
	Deterministic rules (matching emails, IDs, domains).
	String similarity and fuzzy matching (name distance, organisation name normalisation).
	Optional learned entity linking model for larger deployments.
3.	Graph Reasoning & Ranking Models (“Neural Pathways”)
o	Purpose: Prioritise relevant nodes and paths in the graph given a query or context.
o	Outputs:
	Ranked lists of nodes / subgraphs (e.g. most relevant stakeholders, most critical commitments).
	Edge weights indicating influence / importance.
o	Approach:
	Baseline: hand-crafted graph walks and scoring functions.
	Advanced: graph embedding / Graph Neural Network (GNN) models to learn node and relation representations.
4.	Sentiment & Interaction Scoring Models
o	Purpose: Characterise interactions with stakeholders over time.
o	Outputs:
	Sentiment score per interaction (e.g. -1 to +1).
	Aggregated sentiment trends per stakeholder / organisation.
o	Approach:
	Baseline: lexicon / rule-based sentiment with domain wordlists.
	Advanced: fine-tuned text classifier on internal interaction data.
5.	Risk & Alert Scoring Models
o	Purpose: Identify risk signals such as unresolved commitments and sentiment drops.
o	Outputs:
	Risk scores per stakeholder / project / commitment.
	Boolean triggers for defined alert rules.
o	Approach:
	Baseline: rule-driven scoring using thresholds (days overdue, number of negative interactions).
	Advanced: logistic/gradient boosting models trained on labelled “risky vs non-risky” examples.
6.	Personalised Agent Models
o	Purpose: Tailor responses and suggestions to each user.
o	Outputs:
	Recommended actions, summaries, and ranked results conditioned on the user’s role and history.
o	Approach:
	Lightweight preference models (per-user weights in ranking functions; choice of prompts).
	Optional transformer-based contextualisation model for more advanced personalisation.
2.2 Model Tiers
Each model class can be implemented in tiers:
•	Tier 0 – Rule-first
o	Purely deterministic rules and patterns.
o	Minimal resource consumption; good for air-gapped, low-power environments.
•	Tier 1 – Local ML
o	Classical ML or small transformer models running locally.
o	Uses scikit-learn, spaCy, or similar libraries.
•	Tier 2 – Local LLM / Advanced ML
o	Larger local LLMs (e.g. via Ollama) or stronger transformers.
o	Used for extraction, summarisation, and Q&A where higher quality is needed.
The pipeline is designed so that switching tiers is configuration-driven, not architecture-changing.
2.3 Cognitive Memory Tiers
LOGOS models must respect a tiered memory design inspired by human cognition:
•	Short-term (volatile)
o	Ephemeral reasoning traces and intermediate steps scoped to a single pipeline run or user session.
o	Kept in bundle/context memory (e.g. ReasoningBundle traces) and discarded at the end of the session unless explicitly retained.
o	TTL and per-session caps are defined in knowledgebase/rules/memory.yml; no graph writes occur from this tier by default.
•	Mid-term (staging)
o	Managed by the MemoryManager with decay and reinforcement (strength + last_used).
o	Items are promoted from short-term when importance crosses thresholds from knowledgebase/rules/memory.yml or when a user flags them for retention.
o	Each access reinforces strength and refreshes TTL; unused items decay and are evicted.
•	Long-term (canonical)
o	Neo4j + knowledgebase files remain the source of truth for consolidated knowledge.
o	Promotion requires strength/importance thresholds or user confirmation; large justifications are summarised/compressed (summary_max_chars in memory.yml) before persistence to control storage.
•	Consolidation
o	A MemoryConsolidationPipeline (workflows/pipelines.yml) moves data short → mid → long term, applies decay, and hands off long-term candidates to graph upsert routines.
o	Pinned items (pin_user_flagged in memory.yml) bypass decay; demotion thresholds mark obsolete long-term facts for archival.
________________________________________
3. Model Architectures
3.1 NLP Extraction Models
3.1.1 Inputs
•	Plain text from:
o	Parsed documents (DOCX/PDF/TXT/CSV).
o	Transcribed audio (meeting recordings).
o	Pasted notes.
•	Optional metadata:
o	Source type (email, contract, meeting note).
o	Known participants (e.g. from calendar data, if integrated later).
3.1.2 Outputs
Structured extraction bundle:
•	entities:
o	Person: name, email (if available), organisation inferred.
o	Organisation: name, type (customer, supplier, regulator, community).
o	Interaction: type (meeting, call, email), date/time, location if present.
o	Commitment: text, due_date, status (default “proposed”), owner, requester.
o	Project: project identifiers and names.
o	Topic, Issue, Risk: labels and brief descriptions.
•	relationships:
o	Person–WORKS_FOR→Org
o	Person–PARTICIPATED_IN→Interaction
o	Person–MADE→Commitment
o	Commitment–RELATES_TO→Project / Topic
o	Interaction–MENTIONS→(Person / Org / Project / Topic / Contract / Issue)
•	metrics:
o	sentiment score.
o	topical tags / keywords.
3.1.3 Architecture
•	Text Pre-processing Layer
o	Sentence segmentation, tokenisation, normalisation (case, punctuation).
o	Document structure recognition (headings, bullet lists, tables) where applicable.
•	NER & Entity Typing Layer
o	Rule-based patterns (e.g. capitalised sequences with “Pty Ltd”) to spot orgs.
o	Pre-trained NER models (spaCy or transformer-based) fine-tuned on internal data.
o	Heuristics for distinguishing internal vs external people (email domains, org lists).
•	Commitment / Obligation Extraction Layer
o	Pattern-based rules for obligation language (“will provide”, “undertakes to”, “must”, “agreed to”).
o	Optional LLM prompt template for complex cases:
	Input: interaction text + instruction to list commitments.
	Output: structured JSON of commitments.
o	Mapping phrases like “next week” into concrete dates using document date context.
•	Relation Extraction Layer
o	Dependency parsing or relation classifier to link owners, requesters, and projects to commitments.
o	Meeting participation relationships based on mentions and known calendar participants where available.
•	Sentiment Layer
o	Polarity and subjectivity scoring per sentence.
o	Aggregation into per-interaction sentiment with weights on stakeholder-directed sentences.
________________________________________
3.2 Normalisation & Entity Resolution Models
3.2.1 Inputs
•	Extracted entities from NLP layer.
•	Existing graph snapshot or lookup index from Neo4j (names, emails, org IDs, project codes).
3.2.2 Outputs
•	canonical_entities: mapping from extracted mentions → node IDs or “NEW”.
•	operations: planned upsert operations (MERGE statements) with resolved IDs.
3.2.3 Architecture
•	Deterministic Resolver
o	Exact matches on:
	Email addresses.
	Unique IDs / codes (employee ID, project code, contract ID).
o	Domain-based heuristics (e.g. *@company.com → internal Person).
•	Fuzzy Matcher
o	Normalise names and organisation strings (strip punctuation, case, suffixes like Pty Ltd).
o	Compute similarity scores (e.g. Levenshtein, Jaro-Winkler) between extracted entity and existing candidates.
o	Use configurable thresholds for auto-merge vs human-review.
•	Disambiguation & Tie-breaking
o	Use context (organisation, role, project, location) to pick between multiple similar candidates.
o	Optionally a simple classifier (logistic regression) trained on labelled “same vs different entity” pairs.
•	Output Builder
o	Returns resolved IDs plus a confidence score per mapping.
o	For low-confidence cases, flag for preview UI so the user can correct before commit.
________________________________________
3.3 Graph Reasoning & Ranking Models (“Neural Pathways”)
3.3.1 Inputs
•	Graph structure from Neo4j:
o	Nodes (Persons, Orgs, Projects, Commitments, Interactions, Issues, Risks, Topics, Agents).
o	Relationships as per schema.
•	Query context:
o	e.g. “Stakeholder X”, “Project Y”, “Commitments due in next 7 days”.
o	Optionally user context (who is asking).
3.3.2 Outputs
•	Ranked nodes / subgraphs relevant to the query.
•	Edge weights representing influence or importance.
•	Optional “explanation paths” (top k paths that justify ranking).
3.3.3 Architecture
•	Baseline Graph Scoring
o	Hand-crafted scores combining:
	Topology: degree centrality, betweenness, path length.
	Attributes: recency of interactions, sentiment averages, number of open commitments.
o	Example: Stakeholder risk score = f(open commitments, overdue count, recent sentiment, number of projects, escalation flags).
•	Graph Embedding / GNN (Optional Tier 1/2)
o	Node embeddings:
	Use Node2Vec / DeepWalk or GCN/GAT to learn embeddings based on graph structure and node attributes.
o	Application:
	Similar stakeholder search (nearest neighbours in embedding space).
	Improved ranking of “relevant stakeholders for this project”.
•	Path Reasoning & Explanation
o	Path search (e.g. k-shortest paths) between key nodes:
	Stakeholder ↔ Project ↔ Issues ↔ Outcomes.
o	Explanation generation:
	For a given stakeholder risk score, list the interactions and commitments that contributed most.
________________________________________
3.4 Sentiment & Interaction Scoring Models
3.4.1 Inputs
•	Interaction-level text (e.g. meeting notes, emails).
•	Extracted entities (to differentiate stakeholder-targeted language from internal chatter).
3.4.2 Outputs
•	sentiment_score: numeric score per interaction.
•	sentiment_label: e.g. positive / neutral / negative.
•	Aggregations:
o	Rolling average sentiment per stakeholder/org over time.
3.4.3 Architecture
•	Rule-based / Lexicon Baseline
o	Use a domain-adapted sentiment lexicon (e.g. amplify “delay”, “concern”, “risk”, “issue”).
o	Weight sentences directed at the stakeholder more heavily.
•	Supervised Sentiment Model (Optional)
o	Fine-tune a transformer classifier on:
	Internal meeting notes labelled by analysts (e.g. “positive outcome”, “tense”, “risk raised”).
o	Provide probability outputs for calibration.
•	Trend Detection
o	Time-series operations:
	Slope of sentiment over last N interactions.
	Detection of runs of negative interactions (for rule-based alerts).
________________________________________
3.5 Risk & Alert Scoring Models
3.5.1 Inputs
•	Graph-derived features:
o	Commitment counts and statuses.
o	Overdue durations.
o	Sentiment trends.
o	Interaction frequency.
o	Issues / risks tagged.
3.5.2 Outputs
•	Risk scores (0–1) per stakeholder/org/project, where 1 = highest risk.
•	Boolean flags triggering alert creation.
3.5.3 Architecture
•	Rule Engine (MVP)
o	IF number_of_overdue_commitments > 0 OR
3 consecutive negative interactions in 14 days → raise alert.
o	Configuration for thresholds in knowledgebase.
•	ML Scoring (Future)
o	Gradient boosting / logistic regression using features above.
o	Output:
	Probability of “stakeholder relationship at risk” or “project at risk”.
o	Requires labelled history (e.g. deals lost, escalations) to train.
________________________________________
3.6 Personalised Agent Models
3.6.1 Inputs
•	User profile:
o	Role, department, typical artefacts (contracts, projects) they care about.
•	User interaction history:
o	Queries, clicked results, accepted / rejected suggestions.
3.6.2 Outputs
•	User-specific:
o	Ranking weights for search results.
o	Prompt variants (concise vs detailed, tone).
o	Default views (e.g. stakeholder-first vs project-first).
3.6.3 Architecture
•	Profile-based Heuristics
o	For a category manager:
	Prioritise vendor / contract nodes.
o	For a project lead:
	Prioritise project / commitment nodes.
•	Implicit Feedback Learning
o	Maintain per-user statistics:
	Which types of results are clicked most.
	Which suggestions are accepted or ignored.
o	Simple online learning:
	Adjust feature weights (e.g. more weight on recency vs sentiment) using bandit-style updates.
•	Prompt Adaptor (when using LLMs)
o	Maintain per-user prompt templates:
	“Summarise for an executive briefing” vs “Summarise with full operational detail”.
o	Over time, adapt based on edits.
________________________________________
4. Training Strategies
4.1 Data Sources
•	Internal sources (for Stakeholder Engagement MVP and future modules):
o	Meeting notes, transcripts, calendar entries.
o	Emails and documents (where privacy / policy allows).
o	CRM / ERP exports (stakeholder lists, project registries, contracts).
o	Historical risk/issue logs.
•	Synthetic & Bootstrapped Data
o	Pattern-generated commitments and stakeholder interactions for initial training.
o	Synthetic “negative examples” (non-commitment sentences) to train extractors.
4.2 Annotation & Labelling
•	Phase 1 – Pattern-based Bootstrapping
o	Use deterministic rules to create silver-labelled data:
	Spots where patterns clearly indicate commitments.
	Clear positive/negative sentiment examples.
•	Phase 2 – Human-in-the-loop Refinement
o	Build small internal labelling sets:
	Mark commitments, owners, due dates in real meeting notes.
	Label stakeholder sentiments per interaction.
	Label risky / non-risky stakeholder cases.
o	Use these to fine-tune:
	Entity and relation extraction.
	Sentiment classifier.
	Risk scoring models (if used).
•	Phase 3 – Continuous Feedback from UI
o	Treat user corrections in preview (e.g. fixing stakeholder name or due date) as labelled data.
o	Log acceptance/rejection of suggestions as implicit labels for ranking / agent models.
4.3 Training Pipelines
•	Offline Training
o	Periodic retraining of:
	Extraction models.
	Sentiment classifiers.
	Risk models (once labelled data exists).
o	Run on dedicated machine / environment, export frozen model artefacts.
•	Online / Incremental Updates
o	For light models (e.g. simple ranking weights), update incrementally as feedback comes in.
o	Retain audit logs of changes in models/weights.
4.4 Evaluation
•	Define metrics per model class:
o	Extraction:
	Precision / recall / F1 for:
	Stakeholders.
	Commitments (detection + due_date).
	Manual spot checks in preview workflow.
o	Sentiment:
	Accuracy / F1 vs human labels.
	Correlation with practical outcomes (complaints, escalation).
o	Risk / Alerts:
	Precision of alerts (how often alerts are actually useful).
	Reduction in overdue commitments vs baseline.
o	Agents:
	User satisfaction scores (explicit rating).
	Time saved (proxy: reduction in search iterations per query).
________________________________________
5. Deployment and Maintenance
5.1 Model Packaging
•	Models are packaged as Python modules / services with clear interfaces:
o	extract(text, metadata) → extraction_bundle
o	resolve(extraction_bundle, graph_snapshot) → canonical_bundle
o	score_sentiment(text) → sentiment_score
o	score_risk(entity_id) → risk_score
•	Larger models may run in separate worker processes (e.g. a local LLM via HTTP), called by the main FastAPI app.
5.2 Environment Profiles
•	Minimal profile (rule-first):
o	Only deterministic rules + lightweight NLP.
o	No GPU required.
•	Enhanced profile (local ML):
o	Adds spaCy / small transformer models for better extraction and sentiment.
•	Advanced profile (local LLM):
o	Connects to a local LLM host (e.g. Ollama) via HTTP for:
	Complex extraction.
	Summarisation.
	Natural language Q&A and explanation.
Profiles are selected via configuration in the knowledgebase.
5.3 Versioning & Rollback
•	Each model artefact has:
o	Semantic version (major.minor.patch).
o	Metadata: training data snapshot, date, hyperparameters.
•	Deployment procedure:
o	Stage new model version → test on a validation suite → promote to production.
o	Keep previous model versions for rollback.
5.4 Monitoring
•	Track, at minimum:
o	Latency per model call.
o	Error rates (e.g. timeouts, exceptions).
o	Distribution of outputs (e.g. sentiment scores over time – catch drift).
•	Provide logs suitable for forensic analysis in case of incorrect output.
________________________________________
6. Ethical Considerations
6.1 Privacy & Security
•	Training data may contain sensitive stakeholder information. Requirements:
o	Pseudonymise where possible for model training.
o	Ensure only authorised staff can access raw training data.
o	Restrict model outputs from leaking information to unauthorised users (enforce access control before answering queries).
•	For local LLMs, ensure no data leaves the environment (no remote calls unless explicitly configured and approved).
6.2 Bias & Fairness
•	Risk that models learn biased patterns from historical data (e.g. treating some stakeholder groups as “higher risk” purely based on correlation).
Mitigations:
•	Regularly audit outputs for disparity across stakeholder types.
•	Allow configuration of hard constraints / overrides where needed:
o	e.g. avoid using protected attributes in risk scoring features.
•	Provide explanations with outputs so humans can review and contest decisions.
________________________________________
7. Appendices
•	Appendix A – Model-to-Component Mapping
o	NLP Extraction → logos/nlp/
o	Normalisation & Entity Resolution → logos/normalise/
o	Graph I/O & Reasoning → logos/graphio/ + reasoning module.
o	Sentiment & Risk Models → logos/models/scoring/
o	Agent Logic → logos/agents/
•	Appendix B – Example Prompts (when using LLMs)
o	Commitment extraction prompt.
o	Meeting summary prompt.
o	Risk explanation prompt.
•	Appendix C – Future Extensions
o	Domain-specific models for:
	Contract clause classification.
	ESG metric extraction.
	Governance / policy compliance checks.
