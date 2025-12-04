Knowledgebase & Prompt Design Guide
Product: LOGOS – Cognitive Engine + Stakeholder Engagement MVP
________________________________________
1. Introduction
1.1 Purpose
This document defines how LOGOS manages:
•	The knowledgebase (Forms, Concepts, Topics, rules, thresholds, ontologies, lexicons).
•	Prompts and AI instructions used by extraction, reasoning, and agents.
It is the blueprint for how the “LOGOS brain” is configured, extended, and allowed to evolve over time.
1.2 Scope
Covers:
•	Directory and file structure for the knowledgebase.
•	Data formats (YAML/JSON) and conventions.
•	Prompt templates for extraction, reasoning, summarisation, agents.
•	Representation of Forms / Concepts / Particulars / Dialectical Lines.
•	Rules and thresholds (alerts, scoring) with learning hooks.
•	Versioning and governance of knowledge changes.
It is designed to integrate with:
•	Graph Schema & Knowledge Model Specification
•	AI Model Design Document
•	System Architecture Document (SAD)
•	Pipeline & Workflow Design
•	Use Case Document / DFD & ERD
________________________________________
2. Role of the Knowledgebase
The knowledgebase is the control layer for LOGOS Core. It:
•	Defines what entities and relationships LOGOS understands.
•	Encodes domain semantics (Forms, Concepts, taxonomies).
•	Controls how text is interpreted and how prompts are constructed.
•	Provides rule and threshold parameters for scoring and alerts.
•	Holds learned parameters that change as the system adapts.
The codebase should be as generic as possible; the knowledgebase should hold domain-specific logic.
________________________________________
3. Physical Structure
Recommended directory layout (under logos/knowledgebase/):
•	domain_profiles/
o	stakeholder_engagement.yml
o	contracts_governance.yml (future)
o	esg_analytics.yml (future)
•	concepts/
o	forms.yml
o	stakeholder_types.yml
o	risk_categories.yml
o	issue_categories.yml
o	outcome_types.yml
•	topics/
o	topics.yml // topic taxonomy used in extraction and tagging
•	lexicons/
o	sentiment.yml
o	obligation_phrases.yml
o	risk_phrases.yml
o	synonyms.yml
•	prompts/
o	extraction_interaction.yml
o	extraction_commitments.yml
o	summary_interaction.yml
o	reasoning_risk_explanation.yml
o	agent_briefing.yml
•	rules/
o	alerts.yml
o	scores.yml
•	models/
o	tiers.yml // rule_only | local_ml | local_llm per task
•	workflows/
o	pipelines.yml // pipeline definitions (IDs, stages)
•	versioning/
o	schema_version.yml
o	changelog.md
This structure must be stable so the pipelines and services can reliably load the right pieces.
________________________________________
4. Domain Profiles
A domain profile bundles everything for a particular use case.
Example: domain_profiles/stakeholder_engagement.yml
id: stakeholder_engagement
name: "Stakeholder Engagement"
description: "Stakeholder mapping, interactions, commitments, issues, risks, outcomes."

forms:
  enabled:                      # Which Forms are active in this domain
    - Stakeholder
    - Organisation
    - Project
    - Interaction
    - Commitment
    - Issue
    - Risk
    - Outcome
    - Topic

concept_sets:
  - stakeholder_types
  - risk_categories
  - issue_categories
  - outcome_types

topics:
  file: "../topics/topics.yml"

lexicons:
  sentiment: "../lexicons/sentiment.yml"
  obligation_phrases: "../lexicons/obligation_phrases.yml"
  risk_phrases: "../lexicons/risk_phrases.yml"
  synonyms: "../lexicons/synonyms.yml"

prompts:
  extraction_interaction: "../prompts/extraction_interaction.yml"
  extraction_commitments: "../prompts/extraction_commitments.yml"
  summary_interaction: "../prompts/summary_interaction.yml"
  risk_explanation: "../prompts/reasoning_risk_explanation.yml"
  agent_briefing: "../prompts/agent_briefing.yml"

rules:
  alerts: "../rules/alerts.yml"
  scores: "../rules/scores.yml"

models:
  tiers: "../models/tiers.yml"

pipelines:
  definition: "../workflows/pipelines.yml"
Switching domains is mostly a matter of changing the active profile in config.
________________________________________
5. Forms, Concepts, Topics
5.1 Forms (concepts/forms.yml)
Defines the core Forms LOGOS reasons about.
forms:
  - id: form_stakeholder
    name: "Stakeholder"
    description: "Any person or organisation with interest or influence."
    node_labels: ["Person", "Org"]
  - id: form_interaction
    name: "Interaction"
    description: "Any observed interaction or communication."
    node_labels: ["Interaction"]
  - id: form_commitment
    name: "Commitment"
    description: "Engagement actions and obligations arising from interactions."
    node_labels: ["Commitment"]
  - id: form_issue
    name: "Issue"
  - id: form_risk
    name: "Risk"
  - id: form_outcome
    name: "Outcome"
  - id: form_topic
    name: "Topic"
  - id: form_agent
    name: "Agent"
These are used by extraction and reasoning pipelines as the “Platonic” categories.
5.2 Concept Sets (stakeholder_types.yml, risk_categories.yml, etc.)
Example: concepts/stakeholder_types.yml
stakeholder_types:
  - id: st_supplier
    name: "Supplier"
    description: "External organisation providing goods or services."
    form_id: form_stakeholder
    applies_to: ["Org"]
  - id: st_regulator
    name: "Regulator"
    description: "Government or regulatory authority."
    form_id: form_stakeholder
    applies_to: ["Org"]
  - id: st_community_rep
    name: "Community Representative"
    form_id: form_stakeholder
    applies_to: ["Person"]
Example: concepts/risk_categories.yml
risk_categories:
  - id: rc_schedule
    name: "Schedule"
    description: "Schedule and timeline risks."
  - id: rc_commercial
    name: "Commercial"
  - id: rc_reputation
    name: "Reputation"
  - id: rc_esg
    name: "ESG"
5.3 Topics Taxonomy (topics/topics.yml)
topics:
  - id: t_schedule
    name: "Schedule"
    group: "Delivery"
    synonyms: ["timeline", "delivery date", "milestones"]
  - id: t_security
    name: "Security"
    group: "Risk"
    synonyms: ["SOC2", "ISO 27001", "penetration test", "controls"]
  - id: t_community
    name: "Community"
    group: "ESG"
    synonyms: ["local community", "traditional owners", "social licence"]
Topics are the bridge between literal words and Concept categories and can be evolved over time.
________________________________________
6. Lexicons & Patterns
Lexicons capture the system’s current understanding of words/phrases. They are deliberately maintained in the knowledgebase, not hard-coded.
6.1 Sentiment Lexicon (lexicons/sentiment.yml)
tokens:
  positive:
    - "ahead of schedule"
    - "on track"
    - "resolved"
  negative:
    - "delay"
    - "concern"
    - "risk"
    - "complaint"
  intensifiers_positive:
    - "strongly"
    - "significantly"
  intensifiers_negative:
    - "serious"
    - "severe"
    - "major"
Models use this as a baseline; learned classifiers can override, but the list remains visible and editable.
6.2 Obligation Phrases (lexicons/obligation_phrases.yml)
obligation_patterns:
  - pattern: "(will|shall|must|undertakes to)\\s+(deliver|provide|complete)"
    label: "obligation"
    strength: 0.9
  - pattern: "commit(s)? to"
    label: "obligation"
    strength: 0.8

relative_due_date_phrases:
  - phrase: "by the end of {month}"
    interpretation: "last_day_of_month"
  - phrase: "next week"
    interpretation: "next_week"
These are used at extraction time and updated when feedback indicates new patterns.
6.3 Risk Phrases (lexicons/risk_phrases.yml)
risk_signals:
  - phrase: "at risk of"
    category_hint: "rc_schedule"
  - phrase: "may breach"
    category_hint: "rc_commercial"
  - phrase: "community concern"
    category_hint: "rc_esg"
6.4 Synonyms (lexicons/synonyms.yml)
synonyms:
  "baseline":
    - "agreed scope"
    - "initial scope"
  "community":
    - "local community"
    - "traditional owners"
  "delay":
    - "slippage"
    - "push back"
As the system learns new variants (from corrections and usage), they are added here.
________________________________________
7. Prompt Templates
Prompts are stored as YAML with:
•	id: unique ID.
•	task: extraction, summary, reasoning, agent, etc.
•	domain_profile: where applicable.
•	model_hints: suggested model, temperature, max tokens.
•	template: textual prompt with variables.
•	Optional examples (few-shot snippets).
Variables use a simple {{ var_name }} syntax.
7.1 Extraction – Interaction (prompts/extraction_interaction.yml)
id: extraction_interaction
task: extraction
domain_profile: stakeholder_engagement

model_hints:
  preferred_tier: "local_llm"
  temperature: 0.1
  max_tokens: 1024

template: |
  You are LOGOS, an analytical engine that maps real-world interactions into
  structured stakeholder intelligence.

  Forms you must extract:
  - Stakeholder (Person, Organisation)
  - Interaction (meeting, call, email, note)
  - Commitment (obligation or engagement action)
  - Issue (concern raised)
  - Risk (anticipated problem)
  - Topic (tags)
  - Outcome (if clearly stated)

  Use the domain Concepts and Topics as guidance:
  - Stakeholder types: {{ stakeholder_type_list }}
  - Risk categories: {{ risk_category_list }}
  - Topics: {{ topic_list }}

  Input text:
  ---
  {{ text }}
  ---

  Output JSON with this shape:

  {
    "interaction_proposal": {
      "type": "...",
      "at": "...",
      "subject": "...",
      "summary": "...",
      "sentiment_score": <float between -1 and 1>,
      "sentiment_label": "negative|neutral|positive"
    },
    "entities": {
      "persons": [ { "name": "...", "org_name": "...", "hints": {...} } ],
      "orgs": [ { "name": "...", "hints": {...} } ],
      "projects": [ { "name": "...", "code_hint": null } ],
      "commitments": [
        {
          "text": "...",
          "due_date_text": "...",
          "owner_name": "...",
          "requester_name": "...",
          "project_name": "...",
          "contract_hint": null
        }
      ],
      "issues": [ { "title": "...", "description": "...", "category_hint": "..." } ],
      "risks": [ { "title": "...", "description": "...", "category_hint": "..." } ],
      "topics": [ { "name": "...", "topic_id_hint": null } ]
    }
  }

  Do not include any explanatory text outside of the JSON.
The pipeline fills {{ stakeholder_type_list }}, {{ risk_category_list }}, etc. from Concepts and Topics; this ties the LLM to the current ontology.
7.2 Extraction – Commitments (prompts/extraction_commitments.yml)
Used when you want a dedicated commitment pass (e.g. for contracts).
id: extraction_commitments
task: extraction
domain_profile: stakeholder_engagement

model_hints:
  preferred_tier: "local_llm"
  temperature: 0.0
  max_tokens: 1024

template: |
  Extract all commitments (obligations, promises, agreed actions) from the text.

  For each commitment, identify:
  - "text": the obligation in your own concise words.
  - "due_date_text": the phrase describing timing (if any).
  - "owner_name": the party responsible for fulfilling it (internal, if inferable).
  - "requester_name": the party requesting it (if inferable).
  - "topics": list of topic names (from {{ topic_list }} or new if needed).

  Text:
  ---
  {{ text }}
  ---

  Return JSON:

  {
    "commitments": [
      {
        "text": "...",
        "due_date_text": "...",
        "owner_name": "...",
        "requester_name": "...",
        "topics": ["..."]
      }
    ]
  }

  If none, return {"commitments": []}.
7.3 Summarisation – Interaction (prompts/summary_interaction.yml)
id: summary_interaction
task: summary
domain_profile: stakeholder_engagement

model_hints:
  preferred_tier: "local_llm"
  temperature: 0.3
  max_tokens: 512

template: |
  Summarise the interaction for stakeholder governance purposes.

  Focus on:
  - Stakeholders involved
  - Key decisions and commitments
  - Issues and risks raised
  - Next actions and dates

  Keep it concise (max 8 bullet points).

  Interaction text:
  ---
  {{ text }}
  ---

  Output:
  - A short title.
  - Bullet list of key points.
7.4 Reasoning – Risk Explanation (prompts/reasoning_risk_explanation.yml)
id: reasoning_risk_explanation
task: reasoning
domain_profile: stakeholder_engagement

model_hints:
  preferred_tier: "local_llm"
  temperature: 0.2
  max_tokens: 768

template: |
  You are explaining why a stakeholder or project is at risk.

  Context:
  - Stakeholder: {{ stakeholder_name }}
  - Org: {{ org_name }}
  - Project: {{ project_name }}
  - Risk score: {{ risk_score }}

  Evidence (from the graph):
  - Interactions:
  {{ interactions_list }}
  - Commitments:
  {{ commitments_list }}
  - Issues:
  {{ issues_list }}
  - Sentiment trend:
  {{ sentiment_trend }}

  Explain in plain language:
  1. Why the risk is elevated.
  2. Which facts contributed most.
  3. Recommended next steps for engagement.

  Keep the explanation factual and directly tied to the evidence.
7.5 Agent Briefing (prompts/agent_briefing.yml)
id: agent_briefing
task: agent
domain_profile: stakeholder_engagement

model_hints:
  preferred_tier: "local_llm"
  temperature: 0.3
  max_tokens: 1024

template: |
  Prepare a briefing note for {{ audience_type }} about:

  - Stakeholder: {{ stakeholder_name }} ({{ stakeholder_type }})
  - Project: {{ project_name }}
  - Time window: {{ time_window }}

  Use the following structured data from LOGOS:
  - Interactions: {{ interactions_structured }}
  - Commitments: {{ commitments_structured }}
  - Issues and risks: {{ issues_and_risks_structured }}
  - Alerts: {{ alerts_structured }}

  Output sections:
  1. Stakeholder context
  2. Recent developments
  3. Open commitments and risks
  4. Recommended engagement actions

  Use clear, professional language suitable for {{ audience_type }}.
________________________________________
8. Rules & Scores
Rules and thresholds are defined so they can be adjusted automatically based on feedback, rather than hard-coded.
8.1 Alerts Rules (rules/alerts.yml)
alerts:
  unresolved_commitment:
    description: "Commitment older than N days and not done/cancelled."
    enabled: true
    params:
      status_excluded: ["done", "cancelled"]
      age_days:
        initial: 7
        min: 3
        max: 30
        learning: "feedback_regression"

  sentiment_drop:
    description: "Three or more negative interactions within a rolling window."
    enabled: true
    params:
      window_days:
        initial: 14
        min: 7
        max: 60
        learning: "manual"
      min_negative_count:
        initial: 3
        min: 2
        max: 10
        learning: "feedback_regression"
8.2 Scores (rules/scores.yml)
risk_scores:
  stakeholder:
    description: "Stakeholder risk score based on commitments, sentiment, issues."
    weights:
      overdue_commitments:
        initial: 0.4
        min: 0.1
        max: 0.7
        learning: "feedback_regression"
      negative_sentiment:
        initial: 0.3
        min: 0.1
        max: 0.5
        learning: "feedback_regression"
      issues_and_risks:
        initial: 0.3
        min: 0.1
        max: 0.5
        learning: "manual"
Pipelines read these weights and can adjust them over time (within bounds) based on empirical performance.
________________________________________
9. Model Tiers & Task Routing
models/tiers.yml controls which implementation is used for each task:
tasks:
  extraction_interaction:
    tier: "local_llm"        # rule_only | local_ml | local_llm
    fallback_tier: "rule_only"
  extraction_commitments:
    tier: "local_llm"
    fallback_tier: "local_ml"
  sentiment_scoring:
    tier: "local_ml"
    fallback_tier: "rule_only"
  risk_scoring:
    tier: "rule_only"
  summary_interaction:
    tier: "local_llm"
  reasoning_risk_explanation:
    tier: "local_llm"
This allows the same pipeline to run in different environments (no GPU, restricted resources) without code changes.
________________________________________
10. Pipelines Definition (Knowledgebase View)
Aligning with the Pipeline & Workflow Design, workflows/pipelines.yml defines pipelines declaratively:
pipelines:
  interaction_ingest:
    description: "Ingest raw interaction input into preview."
    stages:
      - S1_OBSERVE_RAW
      - S2_PARSE_CONTENT
      - S3_INTERPRET_TEXT
      - S4_QUESTION_AND_ALIGN
      - S5_PREVIEW_MATERIALISE

  interaction_commit:
    description: "Commit edited preview to graph and update learning."
    stages:
      - S6_COMMIT_GRAPH
      - S7_REFLECT_AND_LEARN

  reasoning_alerts:
    description: "Periodic reasoning and alert generation."
    schedule: "every 15m"
    stages:
      - R1_COLLECT_TARGETS
      - R2_COMPUTE_SCORES
      - R3_APPLY_RULES_AND_MODELS
      - R4_MATERIALISE_ALERTS
Each stage name maps to an implementation function in code; this file tells LOGOS which sequence to use.
________________________________________
11. Versioning & Governance
11.1 Version Files
versioning/schema_version.yml:
schema_version: "1.0.0"
knowledgebase_version: "1.0.0"
last_updated: "2025-03-21T04:00:00Z"
versioning/changelog.md:
•	Human-readable log of changes to Forms, Concepts, prompts, rules, thresholds.
11.2 Change Workflow
For production environments:
1.	Propose change (e.g. new risk category, updated alert threshold).
2.	Edit relevant YAML files in branch.
3.	Run tests and evaluation suites:
o	Does extraction still meet metrics?
o	Do alerts have acceptable precision?
4.	Merge and deploy.
5.	LOGOS loads new knowledgebase version on restart or via a reload command.
The learning loops (Section 6 in Pipeline doc) should log any automatic parameter changes back into a machine-readable file and, for sensitive thresholds, into a human-readable audit log.

