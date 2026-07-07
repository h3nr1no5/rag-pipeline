## ADDED Requirements

### Requirement: Sequential backend execution

The system SHALL execute selected RAG backends sequentially, one at a time, in the order specified by the request's `backends` field. Each backend SHALL complete and store its result before the next backend begins execution.

- Backends SHALL NOT execute concurrently
- The execution order SHALL match the order of `request.backends`
- Each backend SHALL update progress and store results independently (same as current behavior)
- The overall task SHALL be marked as "completed" when all backends finish

#### Scenario: Three backends execute in order
- **WHEN** a user submits a query with backends=["cosine", "llamaindex", "langchain"]
- **THEN** cosine backend executes first and stores its result
- **THEN** llamaindex backend executes second and stores its result
- **THEN** langchain backend executes third and stores its result
- **THEN** the task status transitions to "completed"

#### Scenario: Single backend executes
- **WHEN** a user submits a query with only one backend selected
- **THEN** only that backend executes
- **THEN** the task status transitions to "completed" when the backend finishes

#### Scenario: First backend fails, subsequent backends still execute
- **WHEN** the first backend fails with an error
- **THEN** the error is stored in the task results
- **THEN** the next backend in the sequence begins execution
- **THEN** all backends complete (or fail) independently
- **THEN** the task status is "completed" if any backend succeeded, "failed" if all failed

### Requirement: Result isolation

Each backend SHALL return an independent result dictionary containing: `backend` (name), `answer` (text or null), `error` (string or null), and `status`. A failure or timeout in one backend SHALL NOT prevent subsequent backends from executing.

#### Scenario: Middle backend fails
- **WHEN** backend 2 of 3 fails
- **THEN** backend 1's result is stored successfully
- **THEN** backend 3 executes after backend 2's failure
- **THEN** final results contain backend 1 (success), backend 2 (error), backend 3 (success)

### Requirement: Overall query timeout

The sequential execution SHALL have a maximum total wall-clock timeout of 300 seconds. If the total elapsed time from query start exceeds 300 seconds, the task SHALL be cancelled and subsequent backends SHALL NOT execute.

#### Scenario: Total time exceeds 300s
- **WHEN** the first two backends take 160s each (320s total)
- **THEN** the 300s timeout fires before backend 3 starts (or during its execution)
- **THEN** the task status transitions to "failed" with a timeout error
- **THEN** results from backends 1 and 2 are still available

#### Scenario: All backends complete within timeout
- **WHEN** all backends complete within 300 seconds
- **THEN** all results are stored
- **THEN** the task status transitions to "completed"

### Requirement: Frontend polling for sequential results

The frontend SHALL poll `/query/status/{task_id}` to detect new results as they arrive sequentially. Each poll SHALL return all results stored so far (including results from earlier backends in the sequence).

#### Scenario: First result visible before second backend completes
- **WHEN** cosine backend completes (at ~80s)
- **THEN** polling reveals cosine's result in the task status
- **THEN** the frontend stores and renders the cosine answer
- **THEN** llamaindex backend is still executing
- **THEN** subsequent polls continue to show the cosine result alongside the running progress

#### Scenario: All results visible after completion
- **WHEN** all backends complete
- **THEN** polling reveals all results
- **THEN** the frontend displays all answers in order
