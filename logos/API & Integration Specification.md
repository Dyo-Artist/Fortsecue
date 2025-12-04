API & Integration Specification
Product: LOGOS – Cognitive Engine + Stakeholder Engagement MVP
API version: v1 (proposed base path: /api/v1)
________________________________________
1. Purpose and Scope
This specification defines the HTTP API contract for LOGOS Core and the Stakeholder Engagement MVP, including:
•	Base paths, headers, and authentication.
•	Request/response JSON shapes.
•	Error representation and status codes.
•	Endpoint set for:
o	Ingestion → preview → commit.
o	Search & stakeholder/project views.
o	Commitments and alerts.
o	Basic admin/health.
It is designed so:
•	Any UI (web, desktop) or other backend can call LOGOS reliably.
•	LOGOS can be reused as a backend “brain” for other products.
________________________________________
2. General API Design
2.1 Base URL and Versioning
•	Base path (recommended):
/api/v1
Examples:
•	POST /api/v1/ingest/doc
•	GET /api/v1/interactions/{interaction_id}/preview
•	GET /api/v1/search
Versioning:
•	Path-based versioning (/api/v1/...).
•	Backwards-incompatible changes require /api/v2.
2.2 Transport and Encoding
•	Protocol: HTTP/HTTPS (HTTPS strongly recommended outside local dev).
•	Request/Response body: JSON unless explicitly stated (file upload endpoints use multipart/form-data).
•	Character set: UTF-8.
2.3 Authentication
MVP options (choose one and configure):
•	No auth for single-user desktop deployments.
•	Bearer token auth header (recommended basic pattern):
o	Authorization: Bearer <token>
Auth is enforced at reverse proxy or API level; endpoints below assume the request is already authenticated (or intentionally unauthenticated in dev).
2.4 Standard Headers
Clients SHOULD send:
•	Content-Type: application/json (for JSON bodies).
•	Accept: application/json.
For file uploads:
•	Content-Type: multipart/form-data.
2.5 Error Model
On success:
•	HTTP 2xx.
•	Response body is the resource or list (no error wrapper).
On error:
•	HTTP 4xx or 5xx.
•	Response body:
{
  "error": {
    "code": "INVALID_REQUEST",
    "message": "File type not supported",
    "details": {
      "allowed_types": ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]
    }
  }
}
Standard error.code values (non-exhaustive):
•	INVALID_REQUEST (400) – malformed body, invalid parameters.
•	UNAUTHENTICATED (401) – missing/invalid auth.
•	UNAUTHORIZED (403) – forbidden.
•	NOT_FOUND (404) – entity not found.
•	CONFLICT (409) – version or state conflict.
•	UNPROCESSABLE_ENTITY (422) – semantically invalid (e.g. unsupported file).
•	RATE_LIMITED (429) – if enforced later.
•	INTERNAL_ERROR (500) – unexpected server exception.
•	SERVICE_UNAVAILABLE (503) – dependent service down (Neo4j, ASR, LLM, etc.).
2.6 Pagination
For list endpoints:
Query parameters:
•	page (int, default 1, 1-based)
•	page_size (int, default 20, max 200)
Response envelope:
{
  "items": [ /* array of resources */ ],
  "page": 1,
  "page_size": 20,
  "total_items": 134,
  "total_pages": 7
}
________________________________________
3. Data Models (External View)
These are the API payload shapes (simplified) that mirror the graph model.
3.1 Interaction
{
  "id": "ix_00012",
  "type": "meeting",          // meeting | call | email | note | workshop | site_visit
  "subject": "Quarterly review with Acme",
  "summary": "High-level summary text...",
  "at": "2025-03-21T03:45:00Z",
  "location": "Teams",
  "sentiment_score": 0.15,
  "sentiment_label": "neutral",
  "source_uri": "file:///C:/meetings/acme_q1.docx",
  "created_by": "user_123",
  "created_at": "2025-03-21T04:00:00Z",
  "updated_at": "2025-03-21T04:10:00Z"
}
3.2 Person (Stakeholder)
{
  "id": "p_jane_smith",
  "name": "Jane Smith",
  "email": "jane.smith@acme.com",
  "title": "CIO",
  "type": "external",          // internal | external | regulator | community_rep | etc.
  "org_id": "o_acme",
  "influence_score": 0.82
}
3.3 Org
{
  "id": "o_acme",
  "name": "Acme Pty Ltd",
  "legal_name": "Acme Pty Ltd",
  "domain": "acme.com",
  "sector": "mining",
  "type": "supplier",
  "country": "AU",
  "region": "WA"
}
3.4 Commitment
{
  "id": "c_001",
  "interaction_id": "ix_00012",
  "text": "Deliver SOC2 report",
  "due_date": "2025-09-30",
  "status": "proposed",      // proposed | accepted | in_progress | done | cancelled
  "priority": "high",        // low | medium | high | critical
  "owner_person_id": "p_internal_123",
  "requester_person_id": "p_jane_smith",
  "requester_org_id": "o_acme",
  "project_id": "pr_soc2",
  "contract_id": "ct_123",
  "topics": ["t_security", "t_compliance"]
}
3.5 Issue
{
  "id": "i_045",
  "interaction_id": "ix_00012",
  "title": "Delays in dataset delivery",
  "description": "Client has concerns about delays in dataset delivery.",
  "category": "schedule",
  "status": "open",
  "severity": "medium",
  "project_id": "pr_soc2"
}
3.6 Risk (simplified API view)
{
  "id": "r_010",
  "title": "Stakeholder relationship at risk - Acme",
  "description": "Three negative meetings in 14 days and unresolved commitments.",
  "category": "reputation",
  "likelihood": "high",
  "impact": "high",
  "score": 0.9,
  "status": "identified",
  "project_id": "pr_soc2"
}
3.7 Alert
{
  "id": "a_1001",
  "type": "unresolved_commitment",  // unresolved_commitment | sentiment_drop | custom
  "severity": "high",
  "summary": "Commitment c_001 overdue by 10 days",
  "entity_type": "Commitment",
  "entity_id": "c_001",
  "stakeholder_id": "p_jane_smith",
  "org_id": "o_acme",
  "project_id": "pr_soc2",
  "first_detected_at": "2025-10-01T00:00:00Z",
  "last_updated_at": "2025-10-02T01:00:00Z",
  "status": "open"            // open | acknowledged | closed
}
These shapes are used in the endpoint definitions below.
________________________________________
4. Ingestion & Preview Endpoints
4.1 POST /api/v1/ingest/doc
Ingest a document (DOCX/PDF/TXT/CSV) and create a preview.
•	Method: POST
•	Path: /api/v1/ingest/doc
•	Content-Type: multipart/form-data
Request (multipart fields):
•	file (required): binary file.
•	interaction_type (optional): meeting | email | note | workshop | site_visit
If omitted, system infers from context/file or defaults to meeting.
•	interaction_at (optional): ISO 8601 datetime.
•	project_id (optional).
•	contract_id (optional).
•	source_uri (optional override; default = file path in local store).
Example:
Form-data parts:
•	file: acme_q1_meeting.docx
•	interaction_type: meeting
•	interaction_at: 2025-03-21T03:45:00Z
•	project_id: pr_soc2
Success response (201 Created):
{
  "interaction_id": "ix_00012",
  "preview_ready": true
}
Notes:
•	The actual extraction and normalisation can be synchronous (for small docs) or queued; if asynchronous, you may temporarily return preview_ready: false and a status endpoint (not required for MVP if processing is fast enough).
Error responses:
•	400 INVALID_REQUEST – missing file or invalid type.
•	422 UNPROCESSABLE_ENTITY – parsing failed.
________________________________________
4.2 POST /api/v1/ingest/audio
Ingest an audio file for transcription + extraction.
•	Method: POST
•	Path: /api/v1/ingest/audio
•	Content-Type: multipart/form-data
Request fields:
•	file (required): audio file (e.g. WAV, MP3).
•	interaction_type (optional, default meeting).
•	interaction_at (optional).
•	project_id, contract_id (optional).
Success response (201):
{
  "interaction_id": "ix_00013",
  "preview_ready": true
}
Error responses similar to /ingest/doc, plus:
•	503 SERVICE_UNAVAILABLE if ASR unavailable.
________________________________________
4.3 POST /api/v1/ingest/text
Ingest a free-text note.
•	Method: POST
•	Path: /api/v1/ingest/text
•	Content-Type: application/json
Request body:
{
  "interaction_type": "note",
  "interaction_at": "2025-03-21T05:00:00Z",
  "project_id": "pr_soc2",
  "contract_id": null,
  "text": "Acme will deliver the SOC2 report by 30 Sep. Jane Smith (Acme) to send draft next week.",
  "skip_extraction": false
}
•	skip_extraction = true will create a simple Interaction without structured extraction/preview.
Success response (201):
{
  "interaction_id": "ix_00014",
  "preview_ready": true
}
If skip_extraction: true, you may bypass preview and directly commit a minimal Interaction.
________________________________________
4.4 GET /api/v1/interactions/{interaction_id}/preview
Retrieve the preview bundle for an interaction.
•	Method: GET
•	Path: /api/v1/interactions/{interaction_id}/preview
Success response (200):
{
  "interaction": {
    "id": "ix_00012",
    "type": "meeting",
    "subject": "Quarterly review with Acme",
    "summary": "High-level auto summary...",
    "at": "2025-03-21T03:45:00Z",
    "sentiment_score": 0.15,
    "sentiment_label": "neutral",
    "source_uri": "file:///C:/meetings/acme_q1.docx"
  },
  "entities": {
    "persons": [
      {
        "temp_id": "tmp_p1",
        "canonical_id": "p_jane_smith",
        "name": "Jane Smith",
        "email": "jane.smith@acme.com",
        "org_id": "o_acme",
        "confidence": 0.98,
        "is_new": false
      }
    ],
    "orgs": [
      {
        "temp_id": "tmp_o1",
        "canonical_id": "o_acme",
        "name": "Acme Pty Ltd",
        "sector": "mining",
        "confidence": 0.95,
        "is_new": false
      }
    ],
    "projects": [
      {
        "temp_id": "tmp_pr1",
        "canonical_id": "pr_soc2",
        "name": "SOC2 Implementation",
        "is_new": false
      }
    ],
    "commitments": [
      {
        "temp_id": "tmp_c1",
        "canonical_id": null,
        "text": "Deliver SOC2 report",
        "due_date": "2025-09-30",
        "status": "proposed",
        "owner_person_id": "p_internal_123",
        "requester_person_id": null,
        "requester_org_id": "o_acme",
        "project_id": "pr_soc2",
        "contract_id": null
      }
    ],
    "issues": [
      {
        "temp_id": "tmp_i1",
        "canonical_id": null,
        "title": "Concerns about audit scope",
        "category": "scope",
        "severity": "medium"
      }
    ],
    "topics": [
      { "id": "t_security", "name": "Security" }
    ]
  }
}
Notes:
•	temp_id is a local identifier only within the preview; canonical_id is the resolved graph ID if matched.
•	The UI uses this to let the user edit/confirm before commit.
Error responses:
•	404 NOT_FOUND – unknown interaction_id or preview expired.
________________________________________
4.5 POST /api/v1/interactions/{interaction_id}/commit
Commit the preview into the graph.
•	Method: POST
•	Path: /api/v1/interactions/{interaction_id}/commit
•	Content-Type: application/json
Request body:
The client sends an edited version of the preview, using temp_ids to indicate which items to create, update, ignore.
{
  "interaction": {
    "subject": "Quarterly review with Acme",
    "summary": "Reviewed SOC2 progress. Acme to deliver report by 30 Sep.",
    "at": "2025-03-21T03:45:00Z"
  },
  "entities": {
    "persons": [
      {
        "temp_id": "tmp_p1",
        "canonical_id": "p_jane_smith",
        "action": "keep"
      }
    ],
    "orgs": [
      {
        "temp_id": "tmp_o1",
        "canonical_id": "o_acme",
        "action": "keep"
      }
    ],
    "projects": [
      {
        "temp_id": "tmp_pr1",
        "canonical_id": "pr_soc2",
        "action": "keep"
      }
    ],
    "commitments": [
      {
        "temp_id": "tmp_c1",
        "canonical_id": null,
        "action": "create",
        "text": "Deliver SOC2 report",
        "due_date": "2025-09-30",
        "status": "accepted",
        "owner_person_id": "p_internal_123",
        "requester_org_id": "o_acme",
        "project_id": "pr_soc2"
      }
    ],
    "issues": [
      {
        "temp_id": "tmp_i1",
        "canonical_id": null,
        "action": "ignore"
      }
    ]
  }
}
Supported action values:
•	create – create a new node (no canonical_id).
•	link / keep – use existing canonical_id, link in this interaction.
•	ignore – do not create/link this item.
Success response (200):
{
  "interaction_id": "ix_00012",
  "committed": true,
  "created": {
    "persons": 0,
    "orgs": 0,
    "projects": 0,
    "commitments": 1,
    "issues": 0
  },
  "linked": {
    "persons": 1,
    "orgs": 1,
    "projects": 1
  }
}
Error responses:
•	400 INVALID_REQUEST – invalid action or inconsistent IDs.
•	409 CONFLICT – interaction already committed and client requested conflicting changes.
________________________________________
5. Search & View Endpoints
5.1 GET /api/v1/search
Combined search over stakeholders, projects, commitments, etc.
•	Method: GET
•	Path: /api/v1/search
Query params:
•	q (required): search text.
•	type (optional, multi or single): person, org, project, commitment, issue, interaction, topic.
•	project_id (optional filter).
•	org_id (optional).
•	page, page_size (pagination).
Success response (200):
{
  "items": [
    {
      "entity_type": "org",
      "score": 0.97,
      "org": {
        "id": "o_acme",
        "name": "Acme Pty Ltd",
        "sector": "mining",
        "type": "supplier"
      }
    },
    {
      "entity_type": "person",
      "score": 0.89,
      "person": {
        "id": "p_jane_smith",
        "name": "Jane Smith",
        "org_id": "o_acme",
        "title": "CIO"
      }
    }
  ],
  "page": 1,
  "page_size": 20,
  "total_items": 2,
  "total_pages": 1
}
Notes:
•	score is a relevance score from search/ranking.
________________________________________
5.2 GET /api/v1/stakeholders/{id}
Stakeholder 360° view (works for Person or Org).
•	Method: GET
•	Path: /api/v1/stakeholders/{id}
Query params:
•	from (optional date) – filter interactions from date.
•	to (optional date).
•	include_graph (bool, default false) – include a small ego network graph.
Success response (200) (shape simplified):
{
  "stakeholder": {
    "entity_type": "person",
    "person": {
      "id": "p_jane_smith",
      "name": "Jane Smith",
      "email": "jane.smith@acme.com",
      "title": "CIO",
      "type": "external",
      "org_id": "o_acme",
      "influence_score": 0.82
    },
    "org": {
      "id": "o_acme",
      "name": "Acme Pty Ltd",
      "type": "supplier"
    }
  },
  "interactions": [
    {
      "id": "ix_00012",
      "type": "meeting",
      "at": "2025-03-21T03:45:00Z",
      "summary": "Reviewed SOC2 progress...",
      "sentiment_score": 0.15,
      "sentiment_label": "neutral",
      "project_ids": ["pr_soc2"],
      "commitment_ids": ["c_001"]
    }
  ],
  "commitments": [
    {
      "id": "c_001",
      "text": "Deliver SOC2 report",
      "due_date": "2025-09-30",
      "status": "accepted",
      "owner_person_id": "p_internal_123",
      "project_id": "pr_soc2"
    }
  ],
  "projects": [
    {
      "id": "pr_soc2",
      "name": "SOC2 Implementation",
      "status": "active"
    }
  ],
  "issues": [],
  "risks": [],
  "sentiment_trend": [
    {
      "at": "2025-02-15T00:00:00Z",
      "sentiment_score": 0.1
    },
    {
      "at": "2025-03-21T03:45:00Z",
      "sentiment_score": 0.15
    }
  ],
  "alerts": [
    {
      "id": "a_1001",
      "type": "unresolved_commitment",
      "severity": "high",
      "summary": "Commitment c_001 overdue by 10 days",
      "status": "open"
    }
  ],
  "ego_graph": {
    "nodes": [
      { "id": "p_jane_smith", "label": "Person" },
      { "id": "o_acme", "label": "Org" },
      { "id": "pr_soc2", "label": "Project" }
    ],
    "edges": [
      { "from": "p_jane_smith", "to": "o_acme", "type": "WORKS_FOR" },
      { "from": "p_jane_smith", "to": "pr_soc2", "type": "INVOLVED_IN" }
    ]
  }
}
If include_graph=false, omit ego_graph.
________________________________________
5.3 GET /api/v1/projects/{id}/map
Project map and stakeholder network.
•	Method: GET
•	Path: /api/v1/projects/{id}/map
Query params:
•	include_graph (bool, default true).
Success response (200):
{
  "project": {
    "id": "pr_soc2",
    "name": "SOC2 Implementation",
    "status": "active",
    "start_date": "2025-01-01",
    "end_date": null
  },
  "stakeholders": [
    {
      "person": {
        "id": "p_jane_smith",
        "name": "Jane Smith",
        "org_id": "o_acme"
      },
      "role_type": "decision_maker",
      "is_primary": true
    }
  ],
  "orgs": [
    {
      "id": "o_acme",
      "name": "Acme Pty Ltd",
      "type": "supplier"
    }
  ],
  "commitments": [
    {
      "id": "c_001",
      "text": "Deliver SOC2 report",
      "due_date": "2025-09-30",
      "status": "accepted",
      "owner_person_id": "p_internal_123"
    }
  ],
  "issues": [],
  "risks": [],
  "ego_graph": {
    "nodes": [ /* project-centric graph nodes */ ],
    "edges": [ /* relationships */ ]
  }
}
________________________________________
6. Commitments & Alerts Endpoints
6.1 GET /api/v1/commitments
Commitment list for tracking/follow-up.
•	Method: GET
•	Path: /api/v1/commitments
Query params:
•	owner_person_id (optional).
•	stakeholder_id (optional).
•	org_id (optional).
•	project_id (optional).
•	status (optional; can be comma-separated list).
•	due_before, due_after (dates).
•	overdue (bool; if true, filter to overdue).
•	page, page_size.
Success response (200):
{
  "items": [
    {
      "id": "c_001",
      "text": "Deliver SOC2 report",
      "due_date": "2025-09-30",
      "status": "accepted",
      "priority": "high",
      "owner_person_id": "p_internal_123",
      "requester_org_id": "o_acme",
      "project_id": "pr_soc2",
      "created_at": "2025-03-21T04:10:00Z"
    }
  ],
  "page": 1,
  "page_size": 20,
  "total_items": 1,
  "total_pages": 1
}
________________________________________
6.2 PATCH /api/v1/commitments/{id}
Update commitment status and fields.
•	Method: PATCH
•	Path: /api/v1/commitments/{id}
•	Content-Type: application/json
Request body (one or more fields):
{
  "status": "done",
  "due_date": "2025-09-30",
  "owner_person_id": "p_internal_123"
}
Success response (200):
{
  "id": "c_001",
  "text": "Deliver SOC2 report",
  "due_date": "2025-09-30",
  "status": "done",
  "priority": "high",
  "owner_person_id": "p_internal_123",
  "requester_org_id": "o_acme",
  "project_id": "pr_soc2"
}
Error responses:
•	404 NOT_FOUND.
•	409 CONFLICT (if you later add optimistic concurrency/versioning).
________________________________________
6.3 GET /api/v1/alerts
List current alerts.
•	Method: GET
•	Path: /api/v1/alerts
Query params:
•	type (optional; e.g. unresolved_commitment, sentiment_drop).
•	severity (optional; low|medium|high|critical).
•	status (optional; open|acknowledged|closed).
•	owner_person_id (optional; where applicable).
•	stakeholder_id, org_id, project_id (optional).
•	page, page_size.
Success response (200):
{
  "items": [
    {
      "id": "a_1001",
      "type": "unresolved_commitment",
      "severity": "high",
      "summary": "Commitment c_001 overdue by 10 days",
      "entity_type": "Commitment",
      "entity_id": "c_001",
      "stakeholder_id": "p_jane_smith",
      "org_id": "o_acme",
      "project_id": "pr_soc2",
      "first_detected_at": "2025-10-01T00:00:00Z",
      "last_updated_at": "2025-10-02T01:00:00Z",
      "status": "open"
    }
  ],
  "page": 1,
  "page_size": 20,
  "total_items": 1,
  "total_pages": 1
}
(Optional future):
•	PATCH /api/v1/alerts/{id} to mark as acknowledged/closed.
________________________________________
7. Admin & Health Endpoints
7.1 GET /api/v1/health
Basic health check.
•	Method: GET
•	Path: /api/v1/health
Success response (200):
{
  "status": "ok",
  "components": {
    "api": "ok",
    "neo4j": "ok",
    "nlp": "ok",
    "llm": "degraded",      // or "ok" / "unavailable"
    "asr": "unavailable"
  },
  "timestamp": "2025-03-21T04:15:00Z"
}
If core dependencies (API itself, Neo4j) are down, return 503.
________________________________________
7.2 GET /api/v1/config/domain
Read-only view of current domain/profile configuration.
•	Method: GET
•	Path: /api/v1/config/domain
Success response (200):
{
  "domain_profile": "stakeholder_engagement",
  "model_tier": "local_ml",     // rule_only | local_ml | local_llm
  "alert_thresholds": {
    "unresolved_commitment_days": 7,
    "sentiment_drop_window_days": 14,
    "sentiment_drop_min_run": 3
  },
  "features": {
    "enable_audio_ingest": true,
    "enable_llm_summaries": false
  }
}
Config mutation can remain filesystem-based for MVP; an admin API for config write can be added later with appropriate controls.
________________________________________
8. Integration with Local AI Services (HTTP Clients)
LOGOS acts as a client to local LLM/ASR/OCR services. For planning purposes, define simple internal contracts:
8.1 LLM Generation (internal client)
•	Method: POST
•	Typical path (configurable): http://localhost:11434/api/generate (example for Ollama style) or custom.
Request (example shape):
{
  "model": "qwen2.5-14b-instruct",
  "prompt": "You are an extraction model...\nText: ...",
  "temperature": 0.1,
  "max_tokens": 1024,
  "stream": false
}
Response:
{
  "model": "qwen2.5-14b-instruct",
  "created_at": "2025-03-21T04:12:00Z",
  "response": "{ \"commitments\": [...] }"
}
LOGOS then parses response into JSON as per its extraction bundle contract.
8.2 ASR (Transcription) (internal client)
•	Method: POST
•	Path (example): http://localhost:5001/transcribe
Request: multipart with audio file.
Response:
{
  "transcript": "Full transcript text...",
  "language": "en",
  "confidence": 0.91
}
These downstream contracts are internal to LOGOS; they are not exposed externally but must be stable enough for local deployment scripts and config.
________________________________________
9. End-to-End Flow Summary (API Perspective)
1.	Ingest
o	Client → POST /api/v1/ingest/doc|audio|text → interaction_id.
2.	Preview
o	Client → GET /api/v1/interactions/{interaction_id}/preview → preview bundle.
3.	User edits + Commit
o	Client → POST /api/v1/interactions/{interaction_id}/commit → counts of created/linked entities.
4.	Search & Explore
o	GET /api/v1/search → entity list.
o	GET /api/v1/stakeholders/{id} → 360° view.
o	GET /api/v1/projects/{id}/map → project map.
5.	Track & Govern
o	GET /api/v1/commitments / PATCH /api/v1/commitments/{id}.
o	GET /api/v1/alerts.
6.	Admin & Ops
o	GET /api/v1/health.
o	GET /api/v1/config/domain.
This specification is consistent with the SRS, SAD, and graph schema, and gives you a clean, stable surface for both the first Stakeholder Engagement UI and any future tools that plug into LOGOS Core.

