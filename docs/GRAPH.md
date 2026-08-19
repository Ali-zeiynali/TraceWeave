# Stage 5 Foundation — Grounded Entity / Relationship / Timeline Graph

v0.5 implements the highest-value subset of Stage 5 without adding Neo4j or another daemon.

## Entity

An entity has canonical name, type, optional aliases/description and confidence. Model normalization is allowed, but merging unrelated names is intentionally conservative.

## Relationship

A relationship stores source entity, predicate, target entity/text, claim ID, source ID and confidence.

**Invariant:** model-produced relationships with a claim ID that does not exist in the current run are discarded.

## Timeline

Timeline events are generated from dates already present on grounded claims. The graph model is not allowed to invent chronology.

## Research graph vs knowledge graph

`research_edges` explain how TraceWeave got somewhere:

- query → source
- source → citation
- source → archive capture
- archive → materialized source
- claim → relationship
- claim → timeline event

Entity/relationship tables represent the knowledge interpretation of supported claims. Keeping the two graphs distinct lets future UI answer both:

- “What do we currently know?”
- “Why did the system investigate this source?”
