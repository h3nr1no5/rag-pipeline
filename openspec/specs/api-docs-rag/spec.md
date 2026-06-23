# API Docs RAG

## Purpose

Define the retrieval-augmented generation pipeline for API documentation, including BM25 tokenization improvements for camelCase identifiers and startup index reloading from the database.

## Requirements

### Requirement: BM25 tokenization SHALL split camelCase identifiers

The BM25 keyword index SHALL tokenize text so that camelCase and PascalCase identifiers are split into their constituent words, enabling queries that use separated words to match compound identifiers.

**Rationale**: The previous tokenizer (`text.lower().split()`) treated identifiers like `StartSelection` as a single token `"startselection"`. A query containing "start" or "selection" as separate words would never match this token. The fix applies regex-based camelCase splitting before whitespace tokenization, applied symmetrically to both index building and query tokenization.

#### Scenario: Method name query with separated words
- **WHEN** the BM25 index contains a method chunk with `function_name="StartSelection"`
- **AND** a user queries `"how to start selection"`
- **THEN** the BM25 search SHALL return the `StartSelection` chunk among the top results

#### Scenario: Acronym + word boundary splits correctly
- **WHEN** the BM25 index contains a chunk with identifier `"PDFParser"`
- **AND** a user queries `"pdf parser"`
- **THEN** the BM25 search SHALL return the chunk (tokens: `"pdf"` and `"parser"` match)

#### Scenario: Single-word identifiers remain unchanged
- **WHEN** the BM25 index contains a chunk with identifier `"initialize"`
- **AND** a user queries `"initialize"`
- **THEN** the BM25 search SHALL return the chunk (single token `"initialize"` matches as before)

### Requirement: Application startup SHALL reload API doc indexes from the database

On application startup, the `ApiDocPipelineManager` SHALL restore all persisted API document indexes from the `ApiDocIndex` table into memory, so that queries can be served without on-the-fly re-ingestion of source files.

#### Scenario: Indexes loaded on startup
- **WHEN** the application starts (lifespan startup completes)
- **AND** there are existing rows in the `ApiDocIndex` table
- **THEN** `ApiDocPipelineManager.load_all_from_db()` SHALL be called
- **AND** `_manager.is_indexed(document_id)` SHALL return `True` for previously indexed documents without re-processing files

#### Scenario: No-op when API docs are disabled
- **WHEN** the application starts with `settings.api_docs_enabled=False`
- **THEN** `load_all_from_db()` SHALL NOT be called