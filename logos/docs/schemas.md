# Bundle schemas

The LOGOS pipeline moves between short-term bundle payloads. The bundle models in
`logos.models.bundles` formalise the contract for each stage while keeping
flexibility for the evolving knowledgebase schema.

- **RawInputBundle**: initial ingest payload that pairs `InteractionMeta` with
  the raw text or file reference plus a content hash. Intended for short-term
  memory only.
- **ParsedContentBundle**: tokenised/parsed view of the input content, including
  optional document structure and language hints.
- **ExtractionBundle**: NLP output with entities (dynamic types from the
  knowledgebase), relationships, and metrics such as sentiment. The raw
  extraction dict is preserved for learning loops.
- **ResolvedBundle**: entity/relationship resolution output with canonical or
  provisional identifiers and action hints (`create|keep|link|ignore`), plus
  `dialectical_lines` for dialectic graph edges. Preview flows commonly map
  this into a `PreviewBundle` for user edits.
- **PreviewBundle**: UI-facing preview snapshot with interaction summary and
  resolved/linked entities; it represents the editable, resolved bundle that is
  returned to clients for review.
- **UpsertBundle**: graph-ready nodes/relationships with provenance, including
  `dialectical_lines` for dialectic relationships; bundles must be fully
  materialised (stable ids for all nodes and relationships referencing those
  ids directly) before commit. **ReasoningBundle / FeedbackBundle** remain
  reserved for reasoning traces and human feedback while keeping the evolving
  schema writable without hard-coding node/relationship types.

Bundles carry `bundle_version` and `processing_version` to allow pipeline stages
and API consumers to reason about compatibility and replay behaviour.
