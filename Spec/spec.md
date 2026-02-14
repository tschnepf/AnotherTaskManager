# Task Hub – v1 Product & Technical Specification
Self-Hosted, Multi-User, AI-Assisted Task Management System  
Target Environment: Docker (Unraid)  
Architecture: Modular, AI-provider agnostic (Local + Cloud capable)

---

# 1. Goals

## Primary Problems to Solve
A) Forgetting tasks  
B) Not being able to find tasks  
C) Task overload / backlog sprawl  

## Design Principles
- Capture must be instant.
- Retrieval must be powerful.
- Organization must be guided, not burdensome.
- AI must assist, never block.
- Backend API is the source of truth for list shaping (filtering, sorting, ordering, pagination, and manual ordering).
- System must support single-user initially but scale to multi-user cleanly.
- All AI must support local OR cloud via pluggable provider system.
- Dependencies and container images must use the latest stable releases available at implementation time and remain on currently supported versions.
- Follow `Spec/dependency-security-checklist.md` for package/image selection, lockfiles, scanning, and patch cadence.

---

# 2. High-Level Architecture

Frontend: React + Vite + PWA  
Backend API: Django + Django REST Framework  
Worker: Celery + Redis  
Database: PostgreSQL + pgvector  
Deployment: Docker Compose (Unraid compatible)

Services:

- db (postgres + pgvector)
- api (django + drf app)
- worker (celery worker)
- redis (queue broker)
- web (react build served via nginx)
- optional local-ai (OpenAI-compatible endpoint)

---

# 3. Core Domain Model

## 3.1 Multi-Tenant Structure

### Organization
- id (uuid)
- name
- created_at

### User
- id (uuid)
- email
- password_hash
- display_name
- role (owner | admin | member)
- organization_id (FK)
- created_at

## 3.2 Tenancy and Access Boundaries

- Every tenant-owned table must include organization_id.
- Every authenticated request resolves user_id, organization_id, and role from the auth token.
- API handlers must scope all reads/writes to organization_id from the token; client-supplied organization_id is ignored.
- Access to resources outside the caller's organization must return 404 (not 403) to avoid cross-tenant resource discovery.
- Service-layer validation must enforce same-organization relations (for example: task.project_id and task.assigned_to_user_id must belong to the same organization as task.organization_id).

---

# 4. Task Model

## 4.1 Task

- id (uuid)
- organization_id (FK)
- created_by_user_id (FK)
- assigned_to_user_id (nullable FK)
- title (string, required)
- description (text, optional)
- intent (enum: task | note | idea | reference)
- area (enum: work | personal)
- project_id (nullable FK)
- status (enum: inbox | next | waiting | someday | done | archived)
- priority (int nullable 1–5)
- due_at (timestamp nullable)
- completed_at (timestamp nullable)
- source_type (enum: email | conversation | self | other)
- source_link (text nullable)
- source_snippet (text nullable)
- created_at
- updated_at

Indexes:
- (organization_id, status)
- (organization_id, project_id)
- full-text index on (title + description)
- vector index for embeddings (pgvector)

Constraints:
- CHECK (priority IS NULL OR priority BETWEEN 1 AND 5)
- CHECK (status <> 'done' OR completed_at IS NOT NULL)
- CHECK (status = 'done' OR completed_at IS NULL)
- due_at and completed_at stored in UTC

---

## 4.2 Project

- id (uuid)
- organization_id
- name
- area (work | personal)
- is_active (bool)
- is_shared (bool, default false)
- created_at

Constraints:
- UNIQUE (organization_id, lower(name))

---

## 4.3 Tag (Optional Cross-Cutting)

- id (uuid)
- organization_id
- name
- color
- created_at

Constraints:
- UNIQUE (organization_id, lower(name))

### TaskTag
- task_id
- tag_id

Constraints:
- PRIMARY KEY (task_id, tag_id)
- FK task_id -> task(id) ON DELETE CASCADE
- FK tag_id -> tag(id) ON DELETE CASCADE

---

## 4.4 Task State Transitions

Allowed transitions:
- inbox -> next | waiting | someday | done | archived
- next -> waiting | someday | done | archived
- waiting -> next | someday | done | archived
- someday -> next | waiting | done | archived
- done -> next | waiting | someday | archived
- archived -> inbox | next | waiting | someday

Transition rules:
- On transition to done, set completed_at=now (UTC) if null.
- On transition out of done, set completed_at=null.
- PATCH /tasks/{id} must reject invalid state transitions with 409.

---

# 5. AI System Design

## 5.1 AI Provider Abstraction

Create interface:

AIProvider:
- generate_completion(prompt, model)
- generate_embedding(text, model)

Implementations:
- LocalProvider (OpenAI-compatible endpoint)
- CloudProvider (OpenAI/Anthropic/etc.)
- HybridProvider (local fallback → cloud)

Controlled by:

ENV:
- AI_MODE = off | local | cloud | hybrid
- AI_LOCAL_BASE_URL
- AI_CLOUD_PROVIDER
- AI_CLOUD_API_KEY
- AI_DEFAULT_MODEL
- AI_DEFAULT_EMBED_MODEL

---

## 5.2 AI Jobs Table

ai_job
- id
- organization_id
- type (suggest_metadata | embed_task | weekly_review | dedupe_check)
- task_id (nullable)
- status (queued | running | succeeded | failed)
- provider_used (local | cloud)
- error_message
- created_at
- updated_at

---

## 5.3 Task AI Suggestions

task_ai_suggestion
- id
- task_id
- suggestion_json
- confidence_score
- provider_used
- model_name
- model_version (nullable)
- input_hash
- applied_at (nullable)
- created_at

Retention and uniqueness:
- Keep history of suggestions (do not overwrite previous rows).
- Latest suggestion is max(created_at) for a task.

Example suggestion_json:
{
  "area": "work",
  "project_id": "uuid",
  "status": "next",
  "priority": 3,
  "tags": ["@computer", "revit"],
  "intent": "task",
  "reasoning": "Mentions follow-up and technical issue."
}

---

## 5.4 Task Embeddings

task_embedding
- id
- task_id
- embedding (vector)
- provider_used
- model_name
- model_version (nullable)
- embedding_dimensions
- input_hash
- is_active (bool, default true)
- created_at

Uses pgvector extension.

Constraints:
- UNIQUE (task_id, model_name, input_hash)
- At most one active embedding per (task_id, model_name).

---

# 6. AI Feature Set (MVP)

## 6.1 Auto Triage Suggestions
Triggered on task creation/update.
Async job.
UI displays:
- ✨ Suggestions ready
- Apply all / Apply selective fields

Confidence thresholds:
- >0.85 auto-apply (optional user setting)
- 0.5–0.85 suggest
- <0.5 ignore

---

## 6.2 Semantic Search

Search bar supports:
- Standard full-text
- Semantic mode toggle

Query flow:
- Generate embedding for query
- Compare against task_embedding
- Rank by similarity
- Combine with filters

Fallback behavior:
- If AI_MODE=off, semantic=true falls back to full-text search.
- If query embedding generation fails or times out, fall back to full-text search.
- Response metadata must include semantic_requested (bool), semantic_used (bool), and fallback_reason (nullable string).

---

## 6.3 Weekly Review Job

Scheduled job:
- Find tasks:
  - inbox older than 7 days
  - waiting older than 14 days
  - next older than 30 days
- Generate summary
- Store as review record

review_summary
- id
- organization_id
- content
- created_at

---

## 6.4 Duplicate Detection

On task create:
- Compare embedding similarity > threshold
- If high similarity:
  - flag potential duplicate
  - UI shows "Similar task exists"

---

# 7. API Endpoints

## 7.1 API Contract Conventions

- Auth: JWT bearer access token + refresh token rotation.
- Organization scoping: all endpoints operate within organization_id from token claims.
- Pagination: page (default 1), page_size (default 25, max 100).
- Sorting: sort field must be in per-endpoint allowlist; order in (asc|desc).
- Query-shaping authority: backend performs filtering, sorting, ordering, pagination, and persisted manual ordering; frontend only sends query params and renders server response order unchanged.
- Timestamps: ISO-8601 UTC.
- Error schema:
{
  "error_code": "string",
  "message": "human readable summary",
  "details": {},
  "request_id": "uuid"
}
- Validation failures return 400, unauthorized 401, forbidden 403, not found 404, invalid state transition 409.

## Auth
POST /auth/login
POST /auth/register
POST /auth/refresh
POST /auth/logout

## Tasks
POST /tasks
GET /tasks
GET /tasks/{id}
PATCH /tasks/{id}
DELETE /tasks/{id}
POST /tasks/{id}/complete
POST /tasks/{id}/reopen
POST /tasks/{id}/apply-ai-suggestion

Filters supported:
- status
- area
- project_id
- tag
- priority_min/max
- due_before/after
- q (text)
- semantic=true
- sort
- order

Filter/semantic rules:
- semantic=true requires q; otherwise return 400.
- semantic ranking is combined with structured filters, never bypasses them.
- If semantic fallback occurs, return metadata fields from section 6.2.
- Any manual task reordering must persist on the backend (for example via position field and reorder endpoint); do not rely on client-only ordering state.

---

## Projects
GET /projects
POST /projects
PATCH /projects/{id}

---

## Tags
GET /tags
POST /tags

---

## Views (Saved Filters)

view
- id
- organization_id
- name
- filter_json
- sort_field
- sort_order
- is_shared (bool)
- created_by

Endpoints:
GET /views
POST /views
DELETE /views/{id}

---

# 8. Frontend UX Structure

## Desktop Layout

Left Sidebar:
- Saved Views
- Inbox
- Work – Next
- Personal – Next
- Waiting
- Someday
- Projects list
- Tags list

Top Bar:
- Global search
- Semantic toggle
- Quick Add button
- User menu

Main Content:
- Filter bar
- Sort dropdown (controls backend query params only)
- Task list table
- Bulk actions
- ✨ suggestion indicators

Bottom:
- Quick Add input (persistent)

---

## Mobile (PWA)

Default route:
Quick Add screen.

Tabs:
- Inbox
- Next
- Search
- Projects

---

# 9. Capture Mechanisms

## 9.1 Quick Add
Minimal required:
- title
- area toggle

Defaults:
- status=inbox

AI runs async.

---

## 9.2 Bookmarklet

JavaScript snippet:
- grabs page title
- grabs URL
- optional selected text
- POST to /tasks

---

## 9.3 Email Capture (Future)

Inbound webhook:
- parse subject
- parse snippet
- create task

---

# 10. Multi-User Behavior

Permissions:
- Owner:
  - full org control (users, billing/settings, projects, tags, views, tasks)
  - can transfer ownership
- Admin:
  - manage users except changing/removing owner
  - manage all projects/tags/views in organization
  - view/edit/delete all tasks in organization
- Member:
  - create/read/update/delete tasks they created
  - can edit tasks assigned_to_user_id=self
  - can view tasks in shared projects
  - cannot manage users or organization settings

Task assignment behavior (v1):
- Owner/Admin can assign tasks to any member in the same organization.
- Member can assign tasks only to self.
- Assignment across organizations is rejected.

Shared collaboration behavior (v1):
- Project.is_shared controls whether non-owners can view tasks in that project.
- Private projects are visible only to creator, admin, and owner.

Future:
- Mentions (@user)

---

# 11. Privacy Controls

Per-organization settings:
- allow_cloud_ai (bool)
- redact_sensitive_patterns (bool)

Per-task:
- allow_cloud_processing (override)

Redaction rules optional:
- emails
- phone numbers
- project codes

---

# 12. Deployment (Docker Compose Outline)

Services:
- db
- redis
- api
- worker
- web
- optional local-ai

Volumes:
- postgres_data
- backups

Nightly:
- pg_dump to /mnt/user/backups/taskhub

Operational requirements:
- Add health checks for db, redis, api, worker, and web.
- Run schema migrations (`python manage.py migrate`) during deployment before serving API traffic.
- Define restore process and run at least monthly backup-restore verification.
- Store secrets in environment/secret store; never commit API keys to repo.
- Configure log retention and basic metrics (request latency, queue depth, job failures).
- Lock backend/frontend dependencies and build from lockfiles only.
- Run automated vulnerability scanning for Python, Node, and container images in CI; block release on high/critical findings.
- Run scheduled dependency and base-image update checks at least weekly and apply security patches immediately.
- Apply the exact controls in `Spec/dependency-security-checklist.md` as a release gate.

---

# 13. V1 Scope Summary

Included:
- Multi-user
- Projects + Areas + Status
- Saved Views
- Full-text search
- Semantic search
- AI triage suggestions
- Duplicate detection
- Weekly review summary
- Local/cloud pluggable AI

Not included (future):
- Recurring tasks
- Attachments
- Mobile native apps
- Complex automation rules
- Calendar sync

---

# 14. Future Expansion Ready

Architecture supports:
- RBAC
- Per-project permissions
- Audit logs
- Advanced AI workflows
- Workflow automation engine
- Webhooks / API tokens
- Integrations (Revit, ACC, Email, Slack)

---

END OF SPEC
