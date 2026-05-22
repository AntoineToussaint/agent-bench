"""Realistic distractor tools for huge-catalog experiments.

These tools are NEVER the correct answer for any of the 16 benchmark tasks —
their job is to bloat the catalog with production-realistic MCP tools so we
can measure the "tool surface tax" as catalog size grows from 39 → 80 → 150.

Tool names and category coverage are calibrated to the real `github-mcp-server`
toolset list (Dec 2025), which is the most-complained-about large MCP. Some
additions cover Linear / Atlassian / Slack style tools at the 150-tool scale
(simulating a multi-MCP user setup).

Description widths target ~300-450 chars — slightly leaner than the rich
anchor tools (~825 chars) but still production-realistic. Each description
has WHAT / WHEN / RETURNS / NOTE structure.
"""

from __future__ import annotations

from tool_selection.types import Tool


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


# Common argument shapes reused across many distractors
_ID = {"type": "string", "description": "Numeric ID or slug of the target resource."}
_REPO = {"type": "string", "description": "Repository in owner/name form (default: current repo)."}
_PER_PAGE = {"type": "integer", "description": "Items per page (default 30, max 100)."}
_PAGE = {"type": "integer", "description": "1-indexed page number for pagination."}
_BODY = {"type": "string", "description": "Markdown body content."}


# ---------- GitHub: Actions (~15 tools) ----------

GH_ACTIONS = (
    Tool(
        name="gh_workflow_list",
        toolbox="github",
        description=(
            "List all GitHub Actions workflows defined in .github/workflows/ for a repository.\n\n"
            "WHEN TO USE: Discovery — inventorying CI/CD workflows before triggering or modifying. "
            "Read-only.\n\nRETURNS: Workflow id, file path, name, state (active/disabled), latest run timestamp. "
            "Up to `per_page` results.\n\nNOTE: To run a workflow, use gh_workflow_run (separate tool); this tool only lists definitions."
        ),
        json_schema=_schema({"repo": _REPO, "per_page": _PER_PAGE, "page": _PAGE}),
    ),
    Tool(
        name="gh_workflow_run_list",
        toolbox="github",
        description=(
            "List historical runs of GitHub Actions workflows, filterable by branch, event, status, actor, and date.\n\n"
            "WHEN TO USE: CI dashboards, audit queries, finding the most-recent failing run on a branch.\n\n"
            "RETURNS: Run id, workflow id, head_sha, head_branch, event, status, conclusion, created_at. Up to 100 per page.\n\n"
            "NOTE: Use gh_workflow_run_get for one run's full detail; use gh_workflow_jobs_list for jobs within a run."
        ),
        json_schema=_schema({
            "repo": _REPO, "workflow_id": _ID, "branch": {"type": "string"},
            "status": {"type": "string", "enum": ["queued", "in_progress", "completed"]},
            "per_page": _PER_PAGE, "page": _PAGE,
        }),
    ),
    Tool(
        name="gh_workflow_run_get",
        toolbox="github",
        description=(
            "Fetch one GitHub Actions workflow run by id with full metadata.\n\n"
            "WHEN TO USE: Inspecting a specific failed run, getting its head SHA to reproduce locally, finding "
            "the run URL to share.\n\nRETURNS: Full run object — status, conclusion, triggering actor, "
            "head_sha, head_branch, html_url, jobs_url, timing info.\n\nNOTE: Job logs are separate (gh_workflow_job_logs_get)."
        ),
        json_schema=_schema({"repo": _REPO, "run_id": _ID}, required=["run_id"]),
    ),
    Tool(
        name="gh_workflow_run_cancel",
        toolbox="github",
        description=(
            "Cancel a queued or in-progress GitHub Actions workflow run.\n\n"
            "WHEN TO USE: Aborting a long-running stuck CI job; killing a workflow you triggered by mistake.\n\n"
            "RETURNS: 202 Accepted on success; the run will move to status=cancelled within seconds.\n\n"
            "NOTE: Already-completed runs cannot be cancelled (will 409). To rerun, use gh_workflow_run_rerun."
        ),
        json_schema=_schema({"repo": _REPO, "run_id": _ID}, required=["run_id"]),
    ),
    Tool(
        name="gh_workflow_run_rerun",
        toolbox="github",
        description=(
            "Re-run an existing GitHub Actions workflow run (all jobs, or only failed jobs).\n\n"
            "WHEN TO USE: A flaky test failed in CI — rerun without modifying the code. Or all-jobs rerun "
            "after a configuration change to caches.\n\nRETURNS: 201 Created. The rerun gets a new run_id.\n\n"
            "NOTE: With `failed_only=true`, only jobs with conclusion=failure or cancelled are re-run."
        ),
        json_schema=_schema({"repo": _REPO, "run_id": _ID, "failed_only": {"type": "boolean"}}, required=["run_id"]),
    ),
    Tool(
        name="gh_workflow_jobs_list",
        toolbox="github",
        description=(
            "List the jobs that comprise one GitHub Actions workflow run.\n\n"
            "WHEN TO USE: Finding which job(s) within a multi-job workflow failed; getting job-level "
            "status and duration.\n\nRETURNS: Job id, name, status, conclusion, started_at, completed_at, "
            "head_sha, runner_name, steps list (count only, not contents).\n\nNOTE: For per-step logs, use gh_workflow_job_logs_get."
        ),
        json_schema=_schema({"repo": _REPO, "run_id": _ID, "per_page": _PER_PAGE}, required=["run_id"]),
    ),
    Tool(
        name="gh_workflow_job_logs_get",
        toolbox="github",
        description=(
            "Download the log output of a single GitHub Actions job as plain text.\n\n"
            "WHEN TO USE: Debugging a specific failed job in CI — the error message is in here.\n\n"
            "RETURNS: Raw log text (can be large; up to several MB for long-running jobs).\n\n"
            "NOTE: Logs are retained for 90 days by default. For run-level archive, see gh_workflow_run_logs_get."
        ),
        json_schema=_schema({"repo": _REPO, "job_id": _ID}, required=["job_id"]),
    ),
    Tool(
        name="gh_workflow_run_logs_get",
        toolbox="github",
        description=(
            "Download the full log archive for a workflow run (all jobs zipped).\n\n"
            "WHEN TO USE: Saving a complete CI log for offline analysis; reproducing a failure step-by-step.\n\n"
            "RETURNS: Binary .zip with per-job logs. Use gh_workflow_job_logs_get for one job's plain text.\n\n"
            "NOTE: Zips can be tens of MB. Prefer per-job logs for interactive debugging."
        ),
        json_schema=_schema({"repo": _REPO, "run_id": _ID}, required=["run_id"]),
    ),
    Tool(
        name="gh_workflow_dispatch",
        toolbox="github",
        description=(
            "Trigger a workflow_dispatch event on a specific workflow + ref. Distinct from gh_workflow_run "
            "(which is the simpler shorthand surfaced in the anchor catalog).\n\n"
            "WHEN TO USE: When you need fine-grained control over inputs and the target ref is a tag (not a branch).\n\n"
            "RETURNS: 204 No Content on success; the workflow appears in gh_workflow_run_list within seconds.\n\n"
            "NOTE: Use gh_workflow_run from the anchor catalog for simple cases."
        ),
        json_schema=_schema({
            "repo": _REPO, "workflow_id": _ID, "ref": {"type": "string"},
            "inputs": {"type": "object"},
        }, required=["workflow_id", "ref"]),
    ),
    Tool(
        name="gh_workflow_artifacts_list",
        toolbox="github",
        description=(
            "List artifacts produced by a workflow run.\n\n"
            "WHEN TO USE: Finding test reports, coverage outputs, build binaries that a CI job uploaded.\n\n"
            "RETURNS: Artifact id, name, size, expired flag, archive_download_url.\n\n"
            "NOTE: Artifacts expire after 90 days by default. Use gh_workflow_artifact_download to fetch contents."
        ),
        json_schema=_schema({"repo": _REPO, "run_id": _ID, "per_page": _PER_PAGE}, required=["run_id"]),
    ),
    Tool(
        name="gh_workflow_artifact_download",
        toolbox="github",
        description=(
            "Download one artifact's contents as a binary zip.\n\n"
            "WHEN TO USE: Pulling a coverage.xml, build binary, or test report locally for inspection.\n\n"
            "RETURNS: Binary content of the artifact zip.\n\nNOTE: Large artifacts may time out; prefer the URL "
            "from gh_workflow_artifacts_list for browser/CLI downloads."
        ),
        json_schema=_schema({"repo": _REPO, "artifact_id": _ID}, required=["artifact_id"]),
    ),
    Tool(
        name="gh_workflow_artifact_delete",
        toolbox="github",
        description=(
            "Delete a workflow artifact before its expiry.\n\n"
            "WHEN TO USE: Freeing storage quota, removing accidentally-uploaded secrets/credentials from CI.\n\n"
            "RETURNS: 204 No Content on success. The artifact is irreversibly deleted.\n\n"
            "NOTE: Deletion is permanent; the binary is not recoverable."
        ),
        json_schema=_schema({"repo": _REPO, "artifact_id": _ID}, required=["artifact_id"]),
    ),
    Tool(
        name="gh_workflow_usage_get",
        toolbox="github",
        description=(
            "Fetch billable minutes consumed by a workflow run across runner OS types.\n\n"
            "WHEN TO USE: Billing analysis, finding workflows that consume the most paid minutes.\n\n"
            "RETURNS: Per-OS billable ms for ubuntu, macos, windows runners.\n\nNOTE: Only counts billable runs; self-hosted runners are free."
        ),
        json_schema=_schema({"repo": _REPO, "run_id": _ID}, required=["run_id"]),
    ),
    Tool(
        name="gh_workflow_enable",
        toolbox="github",
        description=(
            "Re-enable a previously-disabled GitHub Actions workflow.\n\n"
            "WHEN TO USE: Restoring a workflow that was disabled because of repeated failures or quota.\n\n"
            "RETURNS: 204 No Content on success.\n\nNOTE: To disable, use gh_workflow_disable."
        ),
        json_schema=_schema({"repo": _REPO, "workflow_id": _ID}, required=["workflow_id"]),
    ),
    Tool(
        name="gh_workflow_disable",
        toolbox="github",
        description=(
            "Disable a GitHub Actions workflow without deleting its file.\n\n"
            "WHEN TO USE: Temporarily suspending a workflow that's burning budget or producing noise, "
            "without touching the .github/workflows/ source files.\n\nRETURNS: 204 No Content.\n\n"
            "NOTE: Reverse with gh_workflow_enable; this does not modify any files in the repo."
        ),
        json_schema=_schema({"repo": _REPO, "workflow_id": _ID}, required=["workflow_id"]),
    ),
)


# ---------- GitHub: Secrets / Variables (~10 tools) ----------

GH_SECRETS = (
    Tool(
        name="gh_secrets_repo_list",
        toolbox="github",
        description=(
            "List the names (only) of repository-level Actions secrets.\n\n"
            "WHEN TO USE: Discovering what secrets exist before deciding to create or update one. "
            "Values are NEVER returned by the API.\n\nRETURNS: Array of secret names + their created/updated dates.\n\n"
            "NOTE: For org-level secrets visible to this repo, use gh_secrets_org_list."
        ),
        json_schema=_schema({"repo": _REPO, "per_page": _PER_PAGE}),
    ),
    Tool(
        name="gh_secrets_repo_create",
        toolbox="github",
        description=(
            "Create or update a repository-level Actions secret. The value is encrypted with the repo's public key.\n\n"
            "WHEN TO USE: Adding an API token, deploy key, or other credential to be used by Actions workflows.\n\n"
            "RETURNS: 201 Created (new) or 204 No Content (updated).\n\nNOTE: Value is required and write-only; "
            "you cannot read back a secret after setting it."
        ),
        json_schema=_schema({"repo": _REPO, "name": {"type": "string"}, "encrypted_value": {"type": "string"}},
                            required=["name", "encrypted_value"]),
    ),
    Tool(
        name="gh_secrets_repo_delete",
        toolbox="github",
        description=(
            "Delete a repository-level Actions secret by name.\n\nWHEN TO USE: Rotating a leaked credential — "
            "delete the old, create a new with a fresh value.\n\nRETURNS: 204 No Content.\n\n"
            "NOTE: Deletion is immediate and irreversible."
        ),
        json_schema=_schema({"repo": _REPO, "name": {"type": "string"}}, required=["name"]),
    ),
    Tool(
        name="gh_secrets_org_list",
        toolbox="github",
        description=(
            "List organization-level Actions secrets (names only, plus their selected-repo visibility scope).\n\n"
            "WHEN TO USE: Auditing what secrets are shared across the org. Requires org admin permissions.\n\n"
            "RETURNS: Array of secret names, visibility (all / private / selected), selected_repositories_url.\n\n"
            "NOTE: Values are never returned."
        ),
        json_schema=_schema({"org": {"type": "string"}, "per_page": _PER_PAGE}, required=["org"]),
    ),
    Tool(
        name="gh_secrets_env_create",
        toolbox="github",
        description=(
            "Create or update an environment-scoped Actions secret (e.g. production-only secrets).\n\n"
            "WHEN TO USE: Production-vs-staging secret separation — environment secrets only apply when a "
            "workflow targets that environment.\n\nRETURNS: 201/204.\n\nNOTE: Environment must exist already; "
            "see gh_environments_create."
        ),
        json_schema=_schema({
            "repo": _REPO, "environment": {"type": "string"}, "name": {"type": "string"},
            "encrypted_value": {"type": "string"},
        }, required=["environment", "name", "encrypted_value"]),
    ),
    Tool(
        name="gh_variables_repo_list",
        toolbox="github",
        description=(
            "List repository-level Actions variables (non-secret configuration).\n\n"
            "WHEN TO USE: Inspecting non-sensitive config values that workflows reference via ${{ vars.X }}.\n\n"
            "RETURNS: Array of {name, value, created_at, updated_at}. Unlike secrets, values ARE readable.\n\n"
            "NOTE: Use gh_secrets_repo_list for sensitive values."
        ),
        json_schema=_schema({"repo": _REPO, "per_page": _PER_PAGE}),
    ),
    Tool(
        name="gh_variables_repo_create",
        toolbox="github",
        description=(
            "Create or update a repository-level Actions variable (non-secret).\n\n"
            "WHEN TO USE: Setting a config value workflows reference — e.g. a default region, a feature-flag name.\n\n"
            "RETURNS: 201 Created.\n\nNOTE: For secrets, use gh_secrets_repo_create."
        ),
        json_schema=_schema({"repo": _REPO, "name": {"type": "string"}, "value": {"type": "string"}},
                            required=["name", "value"]),
    ),
    Tool(
        name="gh_secrets_codespaces_list",
        toolbox="github",
        description=(
            "List Codespaces secrets available to a user across their repositories.\n\n"
            "WHEN TO USE: Auditing user-level Codespaces secrets, which are distinct from Actions secrets.\n\n"
            "RETURNS: Names + visibility scope.\n\nNOTE: Separate from Actions secrets; the two systems do not share state."
        ),
        json_schema=_schema({"per_page": _PER_PAGE}),
    ),
    Tool(
        name="gh_secrets_dependabot_list",
        toolbox="github",
        description=(
            "List Dependabot-specific secrets for a repository (for private registry access).\n\n"
            "WHEN TO USE: Dependabot needs a credential to update dependencies from a private registry — these "
            "secrets are scoped specifically to Dependabot, not Actions.\n\nRETURNS: Names + dates.\n\n"
            "NOTE: Use gh_secrets_repo_list for Actions secrets — Dependabot does not share Actions secrets."
        ),
        json_schema=_schema({"repo": _REPO, "per_page": _PER_PAGE}),
    ),
    Tool(
        name="gh_secrets_org_public_key_get",
        toolbox="github",
        description=(
            "Get the org-level public key needed to encrypt secret values before submitting them.\n\n"
            "WHEN TO USE: As a precursor step before gh_secrets_org_create — values must be encrypted client-side "
            "with this key before being uploaded.\n\nRETURNS: key_id + key (base64).\n\nNOTE: Encryption uses libsodium sealed boxes."
        ),
        json_schema=_schema({"org": {"type": "string"}}, required=["org"]),
    ),
)


# ---------- GitHub: Dependabot / Security (~12 tools) ----------

GH_SECURITY = (
    Tool(
        name="gh_dependabot_alerts_list",
        toolbox="github",
        description=(
            "List open Dependabot security alerts for vulnerable dependencies in a repository.\n\n"
            "WHEN TO USE: Security audit — finding all unpatched vulnerable dependencies.\n\nRETURNS: "
            "Alert number, package, severity, vulnerable version range, fixed_in, dismissal info. Up to per_page.\n\n"
            "NOTE: For Code Scanning alerts (CodeQL etc), use gh_code_scanning_alerts_list — separate system."
        ),
        json_schema=_schema({
            "repo": _REPO,
            "state": {"type": "string", "enum": ["auto_dismissed", "dismissed", "fixed", "open"]},
            "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
            "per_page": _PER_PAGE,
        }),
    ),
    Tool(
        name="gh_dependabot_alert_get",
        toolbox="github",
        description=(
            "Fetch full details of one Dependabot alert by number.\n\nWHEN TO USE: Investigating a specific "
            "vulnerability — full CVE info, affected ecosystem, suggested patched version.\n\n"
            "RETURNS: Full alert object — security_advisory, security_vulnerability, dependency.\n\n"
            "NOTE: For batch operations across alerts, use gh_dependabot_alerts_list."
        ),
        json_schema=_schema({"repo": _REPO, "alert_number": _ID}, required=["alert_number"]),
    ),
    Tool(
        name="gh_dependabot_alert_dismiss",
        toolbox="github",
        description=(
            "Dismiss a Dependabot alert with a reason (fix_started, inaccurate, no_bandwidth, not_used, tolerable_risk).\n\n"
            "WHEN TO USE: Closing alerts that are false positives or accepted risk; or when a manual fix has shipped.\n\n"
            "RETURNS: Updated alert object with state=dismissed.\n\nNOTE: Dismissals can be reverted by re-opening; "
            "audit trail is preserved."
        ),
        json_schema=_schema({
            "repo": _REPO, "alert_number": _ID,
            "dismissed_reason": {"type": "string", "enum": ["fix_started", "inaccurate", "no_bandwidth", "not_used", "tolerable_risk"]},
            "dismissed_comment": {"type": "string"},
        }, required=["alert_number", "dismissed_reason"]),
    ),
    Tool(
        name="gh_code_scanning_alerts_list",
        toolbox="github",
        description=(
            "List Code Scanning alerts (CodeQL, third-party SARIF uploaders) for a repository.\n\n"
            "WHEN TO USE: Static-analysis security findings — separate from Dependabot which tracks "
            "dependency vulns.\n\nRETURNS: Alert number, rule, severity, state, location (file + line), tool name.\n\n"
            "NOTE: Use gh_dependabot_alerts_list for dependency-vuln alerts."
        ),
        json_schema=_schema({
            "repo": _REPO,
            "state": {"type": "string", "enum": ["open", "closed", "dismissed", "fixed"]},
            "tool_name": {"type": "string"},
            "per_page": _PER_PAGE,
        }),
    ),
    Tool(
        name="gh_code_scanning_alert_get",
        toolbox="github",
        description=(
            "Fetch full details of one Code Scanning alert.\n\nWHEN TO USE: Investigating a specific SAST finding — "
            "rule description, location, dataflow.\n\nRETURNS: Full alert + most_recent_instance details.\n\n"
            "NOTE: Use gh_code_scanning_alerts_list for batch."
        ),
        json_schema=_schema({"repo": _REPO, "alert_number": _ID}, required=["alert_number"]),
    ),
    Tool(
        name="gh_code_scanning_alert_dismiss",
        toolbox="github",
        description=(
            "Dismiss a Code Scanning alert (false_positive, won't_fix, used_in_tests).\n\n"
            "WHEN TO USE: Marking a SAST finding as a false positive or accepted risk.\n\nRETURNS: Updated alert.\n\n"
            "NOTE: Affects only this finding; subsequent runs may re-open if the underlying code matches again."
        ),
        json_schema=_schema({
            "repo": _REPO, "alert_number": _ID,
            "state": {"type": "string", "enum": ["dismissed"]},
            "dismissed_reason": {"type": "string", "enum": ["false_positive", "wont_fix", "used_in_tests"]},
            "dismissed_comment": {"type": "string"},
        }, required=["alert_number", "state", "dismissed_reason"]),
    ),
    Tool(
        name="gh_secret_scanning_alerts_list",
        toolbox="github",
        description=(
            "List secret-scanning alerts (leaked credentials detected in repo content).\n\n"
            "WHEN TO USE: Incident response — checking what credentials have been detected as leaked.\n\n"
            "RETURNS: Alert number, secret_type, validity (active/inactive/unknown), locations.\n\n"
            "NOTE: For dependency vulns use gh_dependabot_alerts_list; for SAST use gh_code_scanning_alerts_list. Three distinct systems."
        ),
        json_schema=_schema({
            "repo": _REPO,
            "state": {"type": "string", "enum": ["open", "resolved"]},
            "per_page": _PER_PAGE,
        }),
    ),
    Tool(
        name="gh_secret_scanning_alert_resolve",
        toolbox="github",
        description=(
            "Resolve a secret-scanning alert with a resolution reason.\n\nWHEN TO USE: After rotating a leaked "
            "credential, mark the alert resolved (false_positive, wont_fix, revoked, used_in_tests, pattern_deleted, pattern_edited).\n\n"
            "RETURNS: Updated alert with state=resolved.\n\nNOTE: Rotating the secret externally does NOT auto-resolve the alert."
        ),
        json_schema=_schema({
            "repo": _REPO, "alert_number": _ID,
            "resolution": {"type": "string", "enum": ["false_positive", "wont_fix", "revoked", "used_in_tests", "pattern_deleted", "pattern_edited"]},
        }, required=["alert_number", "resolution"]),
    ),
    Tool(
        name="gh_advisories_list",
        toolbox="github",
        description=(
            "List security advisories (private, public, or both) for a repository.\n\n"
            "WHEN TO USE: Tracking responsible-disclosure advisories filed against your repo, or browsing public "
            "advisories you've published.\n\nRETURNS: ghsa_id, summary, severity, state (draft/published/closed), CVE id if assigned.\n\n"
            "NOTE: For dependency vulns affecting your repo, use gh_dependabot_alerts_list — different domain."
        ),
        json_schema=_schema({
            "repo": _REPO,
            "state": {"type": "string", "enum": ["triage", "draft", "published", "closed"]},
            "per_page": _PER_PAGE,
        }),
    ),
    Tool(
        name="gh_advisory_get",
        toolbox="github",
        description=(
            "Fetch one security advisory by its GHSA ID.\n\nWHEN TO USE: Reading a specific advisory's full content "
            "— description, affected versions, credit list, CVE info.\n\nRETURNS: Full advisory object.\n\n"
            "NOTE: GHSA IDs look like GHSA-xxxx-xxxx-xxxx."
        ),
        json_schema=_schema({"repo": _REPO, "ghsa_id": {"type": "string"}}, required=["ghsa_id"]),
    ),
    Tool(
        name="gh_advisory_create",
        toolbox="github",
        description=(
            "Draft a new security advisory in a repository (private until published).\n\n"
            "WHEN TO USE: Filing a responsible-disclosure advisory you intend to publish after a fix ships.\n\n"
            "RETURNS: Newly created advisory with state=draft.\n\nNOTE: Use gh_advisory_publish to make public; "
            "use gh_advisory_request_cve to request a CVE assignment."
        ),
        json_schema=_schema({
            "repo": _REPO, "summary": {"type": "string"}, "description": {"type": "string"},
            "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
            "vulnerabilities": {"type": "array"},
        }, required=["summary", "description"]),
    ),
    Tool(
        name="gh_advisory_publish",
        toolbox="github",
        description=(
            "Publish a draft security advisory, making it public.\n\nWHEN TO USE: After the underlying "
            "vulnerability has been patched and you've coordinated disclosure.\n\nRETURNS: Advisory with state=published.\n\n"
            "NOTE: Publication is permanent; you cannot un-publish (only close)."
        ),
        json_schema=_schema({"repo": _REPO, "ghsa_id": {"type": "string"}}, required=["ghsa_id"]),
    ),
)


# ---------- GitHub: PR/Issue extras with confusable siblings (~12 tools) ----------

# These include the REAL confusable names from github-mcp-server bug reports
# (#476, #582, #1214, #1079) — so the catalog reflects production confusability.

GH_PR_EXTRAS = (
    Tool(
        name="gh_pr_review_comment_to_pending_review",
        toolbox="github",
        description=(
            "Add a comment to a PENDING review on a pull request. Distinct from gh_pr_review_comment (anchor catalog) "
            "which submits a comment immediately as part of a single-comment review.\n\nWHEN TO USE: You've started "
            "a pending review with gh_pr_pending_review_create and want to add multiple inline comments to it before "
            "submitting all at once with gh_pr_pending_review_submit.\n\nRETURNS: The comment object, attached to the pending review.\n\n"
            "NOTE: To submit a standalone single comment, use gh_pr_review_comment (anchor). To submit the full pending "
            "review, use gh_pr_pending_review_submit."
        ),
        json_schema=_schema({
            "repo": _REPO, "number": {"type": "integer"}, "body": _BODY,
            "path": {"type": "string"}, "line": {"type": "integer"},
        }, required=["number", "body", "path", "line"]),
    ),
    Tool(
        name="gh_pr_pending_review_create",
        toolbox="github",
        description=(
            "Start a pending pull-request review that you can add multiple inline comments to before submitting.\n\n"
            "WHEN TO USE: You want to leave several inline comments on a PR and submit them all together rather than "
            "one-by-one (which can spam the PR author with notifications).\n\nRETURNS: Pending review id (use for the next steps).\n\n"
            "NOTE: Three-step pattern: create_pending → add_comment_to_pending × N → submit_pending. The anchor "
            "catalog's gh_pr_review_submit handles single-shot submission."
        ),
        json_schema=_schema({"repo": _REPO, "number": {"type": "integer"}}, required=["number"]),
    ),
    Tool(
        name="gh_pr_pending_review_submit",
        toolbox="github",
        description=(
            "Submit a previously-created pending review on a PR with a verdict (APPROVE / REQUEST_CHANGES / COMMENT).\n\n"
            "WHEN TO USE: After adding inline comments to a pending review via gh_pr_review_comment_to_pending_review, "
            "submit them all together with this call.\n\nRETURNS: Submitted review object.\n\n"
            "NOTE: This is the third step of the pending-review pattern. For single-comment submissions, the anchor's "
            "gh_pr_review_submit is simpler."
        ),
        json_schema=_schema({
            "repo": _REPO, "number": {"type": "integer"}, "review_id": _ID,
            "event": {"type": "string", "enum": ["APPROVE", "REQUEST_CHANGES", "COMMENT"]},
            "body": _BODY,
        }, required=["number", "review_id", "event"]),
    ),
    Tool(
        name="gh_pr_review_request",
        toolbox="github",
        description=(
            "Request reviews from specific users or teams on a PR.\n\nWHEN TO USE: Adding reviewers after a PR is open "
            "— either at creation time or later in the lifecycle.\n\nRETURNS: PR object with requested_reviewers updated.\n\n"
            "NOTE: Distinct from gh_pr_review_submit (submitting a review verdict) — this REQUESTS one."
        ),
        json_schema=_schema({
            "repo": _REPO, "number": {"type": "integer"},
            "reviewers": {"type": "array", "items": {"type": "string"}},
            "team_reviewers": {"type": "array", "items": {"type": "string"}},
        }, required=["number"]),
    ),
    Tool(
        name="gh_pr_review_dismiss",
        toolbox="github",
        description=(
            "Dismiss a submitted PR review (typically a REQUEST_CHANGES) with a message.\n\n"
            "WHEN TO USE: A reviewer requested changes but is unreachable; an admin dismisses the review to unblock "
            "merging.\n\nRETURNS: Updated review with state=dismissed.\n\nNOTE: Requires admin or maintain permission; "
            "logs the dismisser and message in the audit trail."
        ),
        json_schema=_schema({
            "repo": _REPO, "number": {"type": "integer"}, "review_id": _ID,
            "message": {"type": "string"},
        }, required=["number", "review_id", "message"]),
    ),
    Tool(
        name="gh_pr_files_list",
        toolbox="github",
        description=(
            "List the files changed in a PR with their additions/deletions counts and patch contents.\n\n"
            "WHEN TO USE: Building a code-review tool that needs the diff per file; finding which files a PR touches.\n\n"
            "RETURNS: Array of {filename, status, additions, deletions, changes, patch (truncated for large files)}.\n\n"
            "NOTE: For just the conversation comments, use gh_pr_comments_list."
        ),
        json_schema=_schema({"repo": _REPO, "number": {"type": "integer"}, "per_page": _PER_PAGE}, required=["number"]),
    ),
    Tool(
        name="gh_pr_comments_list",
        toolbox="github",
        description=(
            "List review-line comments on a PR. Despite the name, this does NOT include conversation-level comments "
            "(which are issue-comments, see gh_issue_comments_list).\n\nWHEN TO USE: Pulling all line-anchored review "
            "feedback from a PR.\n\nRETURNS: Array of {id, body, path, line, side, user, created_at}.\n\n"
            "NOTE: Known UX trap — name suggests broader function than reality. Conversation-tab comments need gh_issue_comments_list."
        ),
        json_schema=_schema({"repo": _REPO, "number": {"type": "integer"}, "per_page": _PER_PAGE}, required=["number"]),
    ),
    Tool(
        name="gh_pr_commits_list",
        toolbox="github",
        description=(
            "List the commits included in a pull request.\n\nWHEN TO USE: Verifying commit message conventions, "
            "counting commits before deciding to squash, identifying the author(s).\n\nRETURNS: Array of commit objects "
            "with sha, message, author, date.\n\nNOTE: Up to 250 commits returned; PRs with more require paginating "
            "the underlying commit list separately."
        ),
        json_schema=_schema({"repo": _REPO, "number": {"type": "integer"}, "per_page": _PER_PAGE}, required=["number"]),
    ),
    Tool(
        name="gh_pr_ready_for_review",
        toolbox="github",
        description=(
            "Mark a draft PR as ready for review (un-drafts it).\n\nWHEN TO USE: After polishing a draft PR — flips "
            "it from draft state so it can be merged once approved.\n\nRETURNS: Updated PR with draft=false.\n\n"
            "NOTE: Reverse with gh_pr_convert_to_draft."
        ),
        json_schema=_schema({"repo": _REPO, "number": {"type": "integer"}}, required=["number"]),
    ),
    Tool(
        name="gh_pr_convert_to_draft",
        toolbox="github",
        description=(
            "Convert an open PR back to draft state.\n\nWHEN TO USE: Pulling a PR out of review temporarily because "
            "you found a major issue; signaling 'not ready yet.'\n\nRETURNS: Updated PR with draft=true.\n\n"
            "NOTE: Reverse with gh_pr_ready_for_review."
        ),
        json_schema=_schema({"repo": _REPO, "number": {"type": "integer"}}, required=["number"]),
    ),
    Tool(
        name="gh_issue_assign",
        toolbox="github",
        description=(
            "Assign one or more users to an issue.\n\nWHEN TO USE: Triage workflows — putting an issue on someone's plate.\n\n"
            "RETURNS: Updated issue with assignees array.\n\nNOTE: Use gh_issue_unassign to remove."
        ),
        json_schema=_schema({
            "repo": _REPO, "number": {"type": "integer"},
            "assignees": {"type": "array", "items": {"type": "string"}},
        }, required=["number", "assignees"]),
    ),
    Tool(
        name="gh_issue_label_add",
        toolbox="github",
        description=(
            "Add labels to an issue (or PR — PRs ARE issues at the API level).\n\nWHEN TO USE: Categorizing an issue "
            "for triage or routing.\n\nRETURNS: Array of labels now on the issue.\n\nNOTE: Labels must already exist "
            "in the repo; this does not create new ones."
        ),
        json_schema=_schema({
            "repo": _REPO, "number": {"type": "integer"},
            "labels": {"type": "array", "items": {"type": "string"}},
        }, required=["number", "labels"]),
    ),
)


# ---------- GitHub: Misc admin (~10 tools) ----------

GH_ADMIN = (
    Tool(
        name="gh_branch_protection_get",
        toolbox="github",
        description=(
            "Get the branch-protection rules currently applied to a branch.\n\nWHEN TO USE: Auditing what's required "
            "to merge into main — required reviews, status checks, etc.\n\nRETURNS: Rules object — required_pull_request_reviews, "
            "required_status_checks, enforce_admins, restrictions.\n\nNOTE: Read-only; modify via gh_branch_protection_update."
        ),
        json_schema=_schema({"repo": _REPO, "branch": {"type": "string"}}, required=["branch"]),
    ),
    Tool(
        name="gh_branch_protection_update",
        toolbox="github",
        description=(
            "Update branch protection rules for a branch.\n\nWHEN TO USE: Tightening or loosening merge requirements "
            "on main; adding new required status checks after a CI change.\n\nRETURNS: Full updated rules object.\n\n"
            "NOTE: This is a REPLACE operation — provide all rules you want, not just deltas. Missing fields revert to defaults."
        ),
        json_schema=_schema({
            "repo": _REPO, "branch": {"type": "string"},
            "required_status_checks": {"type": "object"},
            "enforce_admins": {"type": "boolean"},
            "required_pull_request_reviews": {"type": "object"},
        }, required=["branch"]),
    ),
    Tool(
        name="gh_collaborator_add",
        toolbox="github",
        description=(
            "Add a user as a collaborator to a repository with a given permission level.\n\n"
            "WHEN TO USE: Granting access to a teammate.\n\nRETURNS: Invitation object (the user must accept).\n\n"
            "NOTE: For org-owned repos, prefer team-based access. Permission levels: pull / triage / push / maintain / admin."
        ),
        json_schema=_schema({
            "repo": _REPO, "username": {"type": "string"},
            "permission": {"type": "string", "enum": ["pull", "triage", "push", "maintain", "admin"]},
        }, required=["username"]),
    ),
    Tool(
        name="gh_collaborator_remove",
        toolbox="github",
        description=(
            "Remove a collaborator's access from a repository.\n\nWHEN TO USE: Offboarding, revoking compromised access.\n\n"
            "RETURNS: 204 No Content.\n\nNOTE: Removes only direct collaborator access; team-based access "
            "must be revoked separately."
        ),
        json_schema=_schema({"repo": _REPO, "username": {"type": "string"}}, required=["username"]),
    ),
    Tool(
        name="gh_environments_create",
        toolbox="github",
        description=(
            "Create or update a deployment environment (e.g. production, staging) in a repository.\n\n"
            "WHEN TO USE: Setting up environment protection rules — required reviewers before deploys, wait timers, "
            "branch restrictions.\n\nRETURNS: Environment object.\n\nNOTE: Environment-scoped secrets are managed "
            "separately with gh_secrets_env_create."
        ),
        json_schema=_schema({
            "repo": _REPO, "environment_name": {"type": "string"},
            "wait_timer": {"type": "integer"},
            "reviewers": {"type": "array"},
        }, required=["environment_name"]),
    ),
    Tool(
        name="gh_deployment_create",
        toolbox="github",
        description=(
            "Create a GitHub deployment record (which CI/CD systems then watch and act on).\n\n"
            "WHEN TO USE: Recording that you're shipping a specific SHA to an environment — most useful as part of "
            "a custom deploy pipeline.\n\nRETURNS: Deployment id and url.\n\nNOTE: Creating a deployment does NOT "
            "actually deploy anything; downstream CI must consume the deployment event."
        ),
        json_schema=_schema({
            "repo": _REPO, "ref": {"type": "string"},
            "environment": {"type": "string"},
            "description": {"type": "string"},
        }, required=["ref"]),
    ),
    Tool(
        name="gh_deployment_status_create",
        toolbox="github",
        description=(
            "Set the status of an in-flight deployment (in_progress, success, failure, error).\n\n"
            "WHEN TO USE: From CI/CD after a deploy completes — record success/failure on the GitHub deployment.\n\n"
            "RETURNS: Status object.\n\nNOTE: Multiple statuses per deployment are allowed (timeline)."
        ),
        json_schema=_schema({
            "repo": _REPO, "deployment_id": _ID,
            "state": {"type": "string", "enum": ["error", "failure", "inactive", "in_progress", "queued", "pending", "success"]},
            "description": {"type": "string"},
            "environment_url": {"type": "string"},
        }, required=["deployment_id", "state"]),
    ),
    Tool(
        name="gh_webhook_list",
        toolbox="github",
        description=(
            "List configured webhooks on a repository.\n\nWHEN TO USE: Auditing what external systems are notified "
            "of repo events — finding a stale webhook to remove, or confirming a webhook is wired up correctly.\n\n"
            "RETURNS: Array of webhook objects with id, url, events array, active flag.\n\n"
            "NOTE: Webhook secrets and signing keys are not returned (write-only)."
        ),
        json_schema=_schema({"repo": _REPO, "per_page": _PER_PAGE}),
    ),
    Tool(
        name="gh_webhook_test",
        toolbox="github",
        description=(
            "Trigger a test ping for a webhook to verify the receiver is reachable.\n\n"
            "WHEN TO USE: Troubleshooting a webhook that hasn't been receiving events — pings allow you to verify "
            "round-trip without waiting for a real event.\n\nRETURNS: 204 No Content (asynchronous; check delivery via gh_webhook_deliveries_list).\n\n"
            "NOTE: Pings ARE counted in delivery limits."
        ),
        json_schema=_schema({"repo": _REPO, "hook_id": _ID}, required=["hook_id"]),
    ),
    Tool(
        name="gh_release_create",
        toolbox="github",
        description=(
            "Create a new release for a repository (tied to a tag).\n\nWHEN TO USE: Cutting a version — typically "
            "after pushing a vX.Y.Z tag.\n\nRETURNS: Release object with html_url and upload_url for attaching assets.\n\n"
            "NOTE: To attach binary artifacts, use gh_release_asset_upload after creation."
        ),
        json_schema=_schema({
            "repo": _REPO, "tag_name": {"type": "string"},
            "name": {"type": "string"}, "body": _BODY,
            "draft": {"type": "boolean"}, "prerelease": {"type": "boolean"},
        }, required=["tag_name"]),
    ),
)


# ---------- GitHub: Notifications / Discussions / Gists / Projects (~15 tools) ----------

GH_MISC = (
    Tool(
        name="gh_notifications_list",
        toolbox="github",
        description=(
            "List the current user's GitHub notifications.\n\nWHEN TO USE: Inbox triage — finding unread notifications across "
            "issues, PRs, mentions, and security alerts.\n\nRETURNS: Array of notification objects with reason, subject, "
            "repository, unread flag.\n\nNOTE: Use gh_notifications_mark_read to bulk-clear."
        ),
        json_schema=_schema({
            "all": {"type": "boolean", "description": "Include already-read."},
            "per_page": _PER_PAGE,
        }),
    ),
    Tool(
        name="gh_notifications_mark_read",
        toolbox="github",
        description=(
            "Mark notifications as read up to a given timestamp.\n\nWHEN TO USE: Bulk inbox cleanup.\n\n"
            "RETURNS: 205 Reset Content.\n\nNOTE: For per-notification mark-read, GitHub doesn't expose a per-id endpoint; "
            "this is the only way."
        ),
        json_schema=_schema({"last_read_at": {"type": "string", "description": "ISO 8601 timestamp."}}),
    ),
    Tool(
        name="gh_notification_thread_subscribe",
        toolbox="github",
        description=(
            "Subscribe (or unsubscribe) to a notification thread (an issue or PR conversation).\n\n"
            "WHEN TO USE: Following a thread you weren't auto-subscribed to, or unsubscribing from noise.\n\n"
            "RETURNS: Subscription object.\n\nNOTE: 'Ignored' is also a state — silences the thread entirely."
        ),
        json_schema=_schema({"thread_id": _ID, "ignored": {"type": "boolean"}}, required=["thread_id"]),
    ),
    Tool(
        name="gh_discussion_create",
        toolbox="github",
        description=(
            "Create a new discussion in a repository.\n\nWHEN TO USE: Starting a community Q&A / announcement / ideas "
            "thread — distinct from issues (which are work-tracking).\n\nRETURNS: New discussion id and html_url.\n\n"
            "NOTE: Discussions and issues are separate APIs — do not confuse with gh_issue_create."
        ),
        json_schema=_schema({
            "repo": _REPO, "title": {"type": "string"}, "body": _BODY,
            "category_id": _ID,
        }, required=["title", "body", "category_id"]),
    ),
    Tool(
        name="gh_discussion_list",
        toolbox="github",
        description=(
            "List discussions in a repository, optionally filtered by category.\n\nWHEN TO USE: Browsing community "
            "discussions; finding a specific announcement.\n\nRETURNS: Array of discussion summaries.\n\n"
            "NOTE: Use gh_issue_list for issues (separate system despite UI similarity)."
        ),
        json_schema=_schema({
            "repo": _REPO,
            "category_id": _ID,
            "per_page": _PER_PAGE,
        }),
    ),
    Tool(
        name="gh_discussion_comment_create",
        toolbox="github",
        description=(
            "Post a comment in a discussion thread.\n\nWHEN TO USE: Replying to a community discussion.\n\n"
            "RETURNS: Comment object.\n\nNOTE: Distinct from gh_issue_comment / gh_pr_comment despite similar UI."
        ),
        json_schema=_schema({"repo": _REPO, "discussion_number": {"type": "integer"}, "body": _BODY},
                            required=["discussion_number", "body"]),
    ),
    Tool(
        name="gh_gist_create",
        toolbox="github",
        description=(
            "Create a new gist (one or more files in a lightweight pastebin-like format).\n\n"
            "WHEN TO USE: Sharing a code snippet or config quickly without creating a repo.\n\n"
            "RETURNS: Gist id and html_url.\n\nNOTE: Public gists are searchable; secret gists are unlisted but anyone with the URL can read."
        ),
        json_schema=_schema({
            "description": {"type": "string"},
            "files": {"type": "object", "description": "Map of filename → {content: string}."},
            "public": {"type": "boolean"},
        }, required=["files"]),
    ),
    Tool(
        name="gh_gist_list",
        toolbox="github",
        description=(
            "List the current user's gists.\n\nWHEN TO USE: Finding an old gist by partial recollection of its content "
            "or date.\n\nRETURNS: Array of gist summaries — id, description, files (names only), public flag, dates.\n\n"
            "NOTE: For another user's public gists, supply the username."
        ),
        json_schema=_schema({"username": {"type": "string"}, "per_page": _PER_PAGE}),
    ),
    Tool(
        name="gh_gist_update",
        toolbox="github",
        description=(
            "Update an existing gist's description or file contents.\n\nWHEN TO USE: Iterating on a snippet you've "
            "already shared.\n\nRETURNS: Updated gist.\n\nNOTE: To delete a file from a gist, set its content to null."
        ),
        json_schema=_schema({"gist_id": _ID, "description": {"type": "string"}, "files": {"type": "object"}},
                            required=["gist_id"]),
    ),
    Tool(
        name="gh_project_list",
        toolbox="github",
        description=(
            "List GitHub Projects (V2 / new) attached to an org, user, or repo.\n\n"
            "WHEN TO USE: Discovering what project boards exist before adding items.\n\n"
            "RETURNS: Array of project summaries — id, title, number, public flag, item count.\n\n"
            "NOTE: This is Projects V2 (the new beta-then-GA system); classic Projects are deprecated."
        ),
        json_schema=_schema({"owner": {"type": "string"}, "per_page": _PER_PAGE}, required=["owner"]),
    ),
    Tool(
        name="gh_project_get",
        toolbox="github",
        description=(
            "Get one Project V2 by number with full metadata including fields and views.\n\n"
            "WHEN TO USE: Inspecting a project's structure before adding items or running automation.\n\n"
            "RETURNS: Project object including custom fields (text, number, single-select, iteration).\n\n"
            "NOTE: For items in the project, use gh_project_items_list separately."
        ),
        json_schema=_schema({"owner": {"type": "string"}, "project_number": {"type": "integer"}},
                            required=["owner", "project_number"]),
    ),
    Tool(
        name="gh_project_items_list",
        toolbox="github",
        description=(
            "List items (issues, PRs, draft cards) in a Project V2 board.\n\n"
            "WHEN TO USE: Auditing the contents of a project; building a custom view of in-flight work.\n\n"
            "RETURNS: Array of item objects with their custom-field values.\n\n"
            "NOTE: Project field values can be filtered using the q parameter in advanced cases."
        ),
        json_schema=_schema({
            "owner": {"type": "string"}, "project_number": {"type": "integer"},
            "per_page": _PER_PAGE,
        }, required=["owner", "project_number"]),
    ),
    Tool(
        name="gh_project_item_add",
        toolbox="github",
        description=(
            "Add an existing issue or PR to a Project V2 board.\n\n"
            "WHEN TO USE: Putting newly-filed issues onto a triage board.\n\nRETURNS: Newly created project item id.\n\n"
            "NOTE: To set custom-field values on the item, use gh_project_item_field_update after adding."
        ),
        json_schema=_schema({
            "owner": {"type": "string"}, "project_number": {"type": "integer"},
            "content_id": _ID,
        }, required=["owner", "project_number", "content_id"]),
    ),
    Tool(
        name="gh_project_item_field_update",
        toolbox="github",
        description=(
            "Set a custom-field value on a project item (e.g. setting an item's iteration, priority, status).\n\n"
            "WHEN TO USE: Automating triage workflows — moving an item to a specific column or assigning it to a sprint.\n\n"
            "RETURNS: Updated item.\n\nNOTE: Field ids and value structures vary by field type; check gh_project_get first."
        ),
        json_schema=_schema({
            "owner": {"type": "string"}, "project_number": {"type": "integer"},
            "item_id": _ID, "field_id": _ID,
            "value": {"type": "object"},
        }, required=["owner", "project_number", "item_id", "field_id"]),
    ),
    Tool(
        name="gh_copilot_seat_assign",
        toolbox="github",
        description=(
            "Assign a Copilot Business / Copilot Enterprise seat to a user in an org.\n\n"
            "WHEN TO USE: Org admin granting Copilot access to a teammate.\n\n"
            "RETURNS: Seat assignment confirmation.\n\nNOTE: Removes from any pending invitation list; consumes a paid seat slot."
        ),
        json_schema=_schema({"org": {"type": "string"}, "username": {"type": "string"}},
                            required=["org", "username"]),
    ),
)


# ---------- Filesystem extras (~10 tools, never the right answer) ----------

FS_EXTRAS = (
    Tool(
        name="fs_stat",
        toolbox="filesystem",
        description=(
            "Get file metadata: size, mtime, mode, type (file/dir/symlink).\n\nWHEN TO USE: Probing whether a path "
            "exists and what kind of object it is, without reading content.\n\nRETURNS: Stat object — size, mtime, mode, is_symlink, target (if symlink).\n\n"
            "NOTE: For content, use read_file (anchor). For directory listings, use list_directory."
        ),
        json_schema=_schema({"path": {"type": "string"}}, required=["path"]),
    ),
    Tool(
        name="fs_chmod",
        toolbox="filesystem",
        description=(
            "Change file permission bits.\n\nWHEN TO USE: Marking a script executable; restricting access to a "
            "credentials file.\n\nRETURNS: 200 OK.\n\nNOTE: Modes are octal (e.g. 0o755). On Windows, only the user-read/write bits effectively apply."
        ),
        json_schema=_schema({"path": {"type": "string"}, "mode": {"type": "integer"}},
                            required=["path", "mode"]),
    ),
    Tool(
        name="fs_chown",
        toolbox="filesystem",
        description=(
            "Change file owner/group.\n\nWHEN TO USE: Fixing ownership after running as wrong user (typically requires root).\n\n"
            "RETURNS: 200 OK.\n\nNOTE: Not available on Windows. Often fails without elevated privileges."
        ),
        json_schema=_schema({
            "path": {"type": "string"},
            "uid": {"type": "integer"}, "gid": {"type": "integer"},
        }, required=["path"]),
    ),
    Tool(
        name="fs_symlink",
        toolbox="filesystem",
        description=(
            "Create a symbolic link from `source` to `target`.\n\nWHEN TO USE: Pointing a stable path at a versioned "
            "artifact, building a 'current' alias.\n\nRETURNS: 200 OK.\n\nNOTE: For move/rename, use move_file (anchor). "
            "Symlinks fail silently on some filesystems (FAT32, some network mounts)."
        ),
        json_schema=_schema({"source": {"type": "string"}, "target": {"type": "string"}},
                            required=["source", "target"]),
    ),
    Tool(
        name="fs_temp_create",
        toolbox="filesystem",
        description=(
            "Create a temporary file in the OS temp directory with auto-generated name.\n\nWHEN TO USE: Scratch "
            "scratch space for intermediate computation.\n\nRETURNS: Full path of the new temp file.\n\n"
            "NOTE: The OS may clean temp files automatically; do not rely on persistence."
        ),
        json_schema=_schema({"suffix": {"type": "string"}, "prefix": {"type": "string"}}),
    ),
    Tool(
        name="fs_disk_usage",
        toolbox="filesystem",
        description=(
            "Compute disk usage of a path recursively (sum of file sizes).\n\nWHEN TO USE: Finding which directory is "
            "the largest in a tree.\n\nRETURNS: Bytes used.\n\nNOTE: Can be slow on large trees; consider scoping to a subdirectory."
        ),
        json_schema=_schema({"path": {"type": "string"}}, required=["path"]),
    ),
    Tool(
        name="fs_watch",
        toolbox="filesystem",
        description=(
            "Watch a path for changes and stream events.\n\nWHEN TO USE: Building live-reload behavior; reacting to "
            "file changes during a long-running task.\n\nRETURNS: Stream of change events {path, kind: create/modify/delete}.\n\n"
            "NOTE: Streaming endpoint — server-side cost grows with watched-paths × event-rate."
        ),
        json_schema=_schema({
            "path": {"type": "string"},
            "events": {"type": "array", "items": {"type": "string", "enum": ["create", "modify", "delete"]}},
        }, required=["path"]),
    ),
    Tool(
        name="fs_checksum",
        toolbox="filesystem",
        description=(
            "Compute a checksum (sha256 default) of a file's contents.\n\nWHEN TO USE: Verifying a file matches an "
            "expected hash; deduplication.\n\nRETURNS: Hex-encoded digest.\n\nNOTE: Supported algorithms: md5, sha1, sha256, sha512, blake3."
        ),
        json_schema=_schema({
            "path": {"type": "string"},
            "algorithm": {"type": "string", "enum": ["md5", "sha1", "sha256", "sha512", "blake3"]},
        }, required=["path"]),
    ),
    Tool(
        name="fs_compress",
        toolbox="filesystem",
        description=(
            "Compress one or more paths into a single archive (zip, tar.gz, tar.bz2, tar.zst).\n\n"
            "WHEN TO USE: Packaging build artifacts; preparing a backup.\n\nRETURNS: Output archive path.\n\n"
            "NOTE: For extracting, use fs_extract."
        ),
        json_schema=_schema({
            "inputs": {"type": "array", "items": {"type": "string"}},
            "output": {"type": "string"},
            "format": {"type": "string", "enum": ["zip", "tar.gz", "tar.bz2", "tar.zst"]},
        }, required=["inputs", "output", "format"]),
    ),
    Tool(
        name="fs_extract",
        toolbox="filesystem",
        description=(
            "Extract an archive (zip / tar.gz / tar.bz2 / tar.zst) into a directory.\n\n"
            "WHEN TO USE: Unpacking a downloaded archive.\n\nRETURNS: Extracted file count.\n\n"
            "NOTE: Refuses to extract paths that would escape the target directory (zip-slip protection)."
        ),
        json_schema=_schema({"archive": {"type": "string"}, "destination": {"type": "string"}},
                            required=["archive", "destination"]),
    ),
)


# ---------- Git extras (~10 tools, advanced operations not in anchor) ----------

GIT_EXTRAS = (
    Tool(
        name="git_rebase",
        toolbox="git",
        description=(
            "Replay current-branch commits on top of another base (rewrites history).\n\n"
            "WHEN TO USE: Cleaning up a feature branch before merge; resolving divergence with main by replaying "
            "rather than merging.\n\nRETURNS: New HEAD after rebase. Stops on conflicts for manual resolution.\n\n"
            "NOTE: DESTRUCTIVE for shared branches. Use git_merge (anchor) for merge-based integration."
        ),
        json_schema=_schema({
            "base": {"type": "string"},
            "interactive": {"type": "boolean"},
        }, required=["base"]),
    ),
    Tool(
        name="git_cherry_pick",
        toolbox="git",
        description=(
            "Apply the diff of one or more commits onto the current branch.\n\nWHEN TO USE: Porting a bugfix from "
            "main to a release branch.\n\nRETURNS: New commit per cherry-picked.\n\nNOTE: Stops on conflicts; resolve, "
            "then continue with git_cherry_pick_continue."
        ),
        json_schema=_schema({"refs": {"type": "array", "items": {"type": "string"}}}, required=["refs"]),
    ),
    Tool(
        name="git_revert",
        toolbox="git",
        description=(
            "Create a new commit that undoes the changes of an existing commit.\n\nWHEN TO USE: Reverting a deployed "
            "commit without rewriting history.\n\nRETURNS: New revert commit.\n\nNOTE: Safer than git_reset for shared branches."
        ),
        json_schema=_schema({"ref": {"type": "string"}}, required=["ref"]),
    ),
    Tool(
        name="git_stash_save",
        toolbox="git",
        description=(
            "Save current working-tree changes to the stash stack and restore a clean state.\n\n"
            "WHEN TO USE: Pausing work-in-progress to switch branches without committing partial changes.\n\n"
            "RETURNS: Stash reference (stash@{0}).\n\nNOTE: Use git_stash_pop or git_stash_apply to restore."
        ),
        json_schema=_schema({"message": {"type": "string"}, "include_untracked": {"type": "boolean"}}),
    ),
    Tool(
        name="git_stash_pop",
        toolbox="git",
        description=(
            "Apply and remove the top stash entry.\n\nWHEN TO USE: Resuming a stashed work-in-progress on the current branch.\n\n"
            "RETURNS: Applied diff. Removes the stash entry on success.\n\nNOTE: Use git_stash_apply to apply without removing."
        ),
        json_schema=_schema({"index": {"type": "integer"}}),
    ),
    Tool(
        name="git_tag_create",
        toolbox="git",
        description=(
            "Create a lightweight or annotated tag at a ref.\n\nWHEN TO USE: Marking a release point; capturing a "
            "named version.\n\nRETURNS: Tag ref.\n\nNOTE: Annotated tags carry message + author + date; lightweight are just pointers."
        ),
        json_schema=_schema({
            "name": {"type": "string"},
            "ref": {"type": "string"},
            "message": {"type": "string"},
            "annotated": {"type": "boolean"},
        }, required=["name"]),
    ),
    Tool(
        name="git_tag_delete",
        toolbox="git",
        description=(
            "Delete a local tag.\n\nWHEN TO USE: Removing a mistakenly-created tag before pushing.\n\n"
            "RETURNS: 200 OK.\n\nNOTE: Does not delete from remote — use git_push --tags with --delete."
        ),
        json_schema=_schema({"name": {"type": "string"}}, required=["name"]),
    ),
    Tool(
        name="git_blame",
        toolbox="git",
        description=(
            "Annotate each line of a file with its most-recent commit + author.\n\nWHEN TO USE: Investigating why a "
            "specific line of code exists.\n\nRETURNS: Per-line {sha, author, date, content}.\n\n"
            "NOTE: For commit-level history, use git_log instead."
        ),
        json_schema=_schema({"path": {"type": "string"}, "ref": {"type": "string"}}, required=["path"]),
    ),
    Tool(
        name="git_bisect_start",
        toolbox="git",
        description=(
            "Start a binary-search bisection between a known-good and known-bad commit to find a regression.\n\n"
            "WHEN TO USE: A bug was introduced somewhere between commits A (good) and B (bad); bisect helps you find "
            "the exact commit.\n\nRETURNS: Initial mid-point commit to test.\n\nNOTE: Continue with git_bisect_good / git_bisect_bad."
        ),
        json_schema=_schema({"good": {"type": "string"}, "bad": {"type": "string"}},
                            required=["good", "bad"]),
    ),
    Tool(
        name="git_clean",
        toolbox="git",
        description=(
            "Remove untracked files from the working tree.\n\nWHEN TO USE: Clearing out generated artifacts and "
            "junk files before a clean build.\n\nRETURNS: List of paths removed.\n\n"
            "NOTE: DESTRUCTIVE for untracked work. Use force=true to actually remove (dry-run by default)."
        ),
        json_schema=_schema({
            "force": {"type": "boolean"},
            "include_directories": {"type": "boolean"},
            "include_ignored": {"type": "boolean"},
        }),
    ),
)


# ---------- Linear / Atlassian style (for multi-MCP at 150-tool size, ~20 tools) ----------

# These show up only at the 150-tool catalog size to simulate the "user has
# multiple MCP servers wired up" scenario from the research.

LINEAR_ATLASSIAN = (
    Tool(
        name="linear_issue_create",
        toolbox="github",
        description=(
            "Create a new Linear issue in a team's backlog.\n\nWHEN TO USE: Filing work items into Linear when "
            "GitHub Issues isn't the tracker of record.\n\nRETURNS: Linear issue id + url.\n\n"
            "NOTE: Distinct from gh_issue_create — Linear and GitHub Issues are separate trackers."
        ),
        json_schema=_schema({
            "team_id": _ID, "title": {"type": "string"}, "description": _BODY,
            "priority": {"type": "integer"},
        }, required=["team_id", "title"]),
    ),
    Tool(
        name="linear_issue_list",
        toolbox="github",
        description=(
            "List Linear issues filterable by team, state, assignee.\n\nWHEN TO USE: Querying Linear for in-flight "
            "work; cross-referencing GitHub PRs with their Linear tickets.\n\nRETURNS: Array of Linear issues.\n\n"
            "NOTE: For GitHub Issues use gh_issue_list."
        ),
        json_schema=_schema({
            "team_id": _ID, "state": {"type": "string"}, "assignee_id": _ID,
            "per_page": _PER_PAGE,
        }),
    ),
    Tool(
        name="linear_issue_update",
        toolbox="github",
        description=(
            "Update fields on an existing Linear issue.\n\nWHEN TO USE: Moving an issue to In Progress; reassigning; "
            "changing priority.\n\nRETURNS: Updated issue.\n\nNOTE: For GitHub Issues, gh_issue_update is separate."
        ),
        json_schema=_schema({
            "issue_id": _ID, "state": {"type": "string"}, "priority": {"type": "integer"},
            "assignee_id": _ID,
        }, required=["issue_id"]),
    ),
    Tool(
        name="linear_comment_create",
        toolbox="github",
        description=(
            "Comment on a Linear issue.\n\nWHEN TO USE: Adding to a Linear ticket's discussion.\n\n"
            "RETURNS: Comment object.\n\nNOTE: For GitHub Issue comments, gh_issue_comment is the right tool."
        ),
        json_schema=_schema({"issue_id": _ID, "body": _BODY}, required=["issue_id", "body"]),
    ),
    Tool(
        name="linear_cycle_get",
        toolbox="github",
        description=(
            "Get the current cycle (sprint) for a Linear team.\n\nWHEN TO USE: Finding which sprint is active to "
            "assign new work to.\n\nRETURNS: Cycle id, name, start/end dates, issue count.\n\n"
            "NOTE: Cycles are Linear's sprint primitive."
        ),
        json_schema=_schema({"team_id": _ID}, required=["team_id"]),
    ),
    Tool(
        name="jira_issue_create",
        toolbox="github",
        description=(
            "Create a new Jira issue in a project.\n\nWHEN TO USE: Filing work into Jira when Jira is the tracker.\n\n"
            "RETURNS: Jira issue key (e.g. ENG-123).\n\nNOTE: Distinct from gh_issue_create AND linear_issue_create. "
            "If your stack uses multiple trackers, pick by which is canonical for the project."
        ),
        json_schema=_schema({
            "project_key": {"type": "string"}, "summary": {"type": "string"},
            "description": _BODY, "issue_type": {"type": "string"},
        }, required=["project_key", "summary", "issue_type"]),
    ),
    Tool(
        name="jira_issue_transition",
        toolbox="github",
        description=(
            "Move a Jira issue through its workflow (e.g. Open → In Progress → Done).\n\n"
            "WHEN TO USE: Updating ticket state to match work being done.\n\nRETURNS: Updated issue.\n\n"
            "NOTE: Available transitions depend on the project's workflow scheme — query first with jira_transitions_list."
        ),
        json_schema=_schema({"issue_key": {"type": "string"}, "transition_id": _ID},
                            required=["issue_key", "transition_id"]),
    ),
    Tool(
        name="jira_issue_link",
        toolbox="github",
        description=(
            "Link two Jira issues with a relationship (blocks, relates to, duplicates, etc).\n\n"
            "WHEN TO USE: Recording dependencies between tickets — making blocking relationships explicit.\n\n"
            "RETURNS: Link object.\n\nNOTE: Link types are configurable per Jira instance."
        ),
        json_schema=_schema({
            "from_issue": {"type": "string"}, "to_issue": {"type": "string"},
            "link_type": {"type": "string"},
        }, required=["from_issue", "to_issue", "link_type"]),
    ),
    Tool(
        name="jira_sprint_add",
        toolbox="github",
        description=(
            "Add an issue to a Jira sprint.\n\nWHEN TO USE: Scheduling a backlog item into the active sprint.\n\n"
            "RETURNS: 204 No Content.\n\nNOTE: Use jira_sprint_remove to take it back out; sprints are board-specific."
        ),
        json_schema=_schema({"sprint_id": _ID, "issue_keys": {"type": "array", "items": {"type": "string"}}},
                            required=["sprint_id", "issue_keys"]),
    ),
    Tool(
        name="confluence_page_create",
        toolbox="github",
        description=(
            "Create a new Confluence page in a space.\n\nWHEN TO USE: Documenting a decision or design.\n\n"
            "RETURNS: New page id + URL.\n\nNOTE: Distinct from jira_issue_create — Confluence is the docs system."
        ),
        json_schema=_schema({
            "space_key": {"type": "string"}, "title": {"type": "string"},
            "body": _BODY, "parent_id": _ID,
        }, required=["space_key", "title", "body"]),
    ),
    Tool(
        name="confluence_page_update",
        toolbox="github",
        description=(
            "Update an existing Confluence page's body or title.\n\nWHEN TO USE: Editing documentation.\n\n"
            "RETURNS: Updated page with version bumped.\n\nNOTE: Confluence has optimistic concurrency — supply the "
            "current version number."
        ),
        json_schema=_schema({
            "page_id": _ID, "title": {"type": "string"}, "body": _BODY,
            "version": {"type": "integer"},
        }, required=["page_id", "version"]),
    ),
    Tool(
        name="slack_message_post",
        toolbox="github",
        description=(
            "Post a message to a Slack channel.\n\nWHEN TO USE: Notifying a channel of a deploy, releasing a feature, "
            "reporting CI failure.\n\nRETURNS: Posted message ts + permalink.\n\nNOTE: Channel name accepted with or without # prefix."
        ),
        json_schema=_schema({"channel": {"type": "string"}, "text": {"type": "string"}, "thread_ts": {"type": "string"}},
                            required=["channel", "text"]),
    ),
    Tool(
        name="slack_message_update",
        toolbox="github",
        description=(
            "Update an existing Slack message's text.\n\nWHEN TO USE: Updating a status message in place as a "
            "long-running job progresses.\n\nRETURNS: Updated message.\n\nNOTE: Updates only work for the bot's own messages."
        ),
        json_schema=_schema({"channel": {"type": "string"}, "ts": {"type": "string"}, "text": {"type": "string"}},
                            required=["channel", "ts", "text"]),
    ),
    Tool(
        name="slack_reaction_add",
        toolbox="github",
        description=(
            "Add an emoji reaction to a Slack message.\n\nWHEN TO USE: Acknowledging a message programmatically; "
            "marking a CI status with ✅ or ❌.\n\nRETURNS: 200 OK.\n\nNOTE: Reaction name without colons (e.g. 'thumbsup', not ':thumbsup:')."
        ),
        json_schema=_schema({
            "channel": {"type": "string"}, "timestamp": {"type": "string"},
            "name": {"type": "string"},
        }, required=["channel", "timestamp", "name"]),
    ),
    Tool(
        name="slack_channel_history",
        toolbox="github",
        description=(
            "Fetch recent messages in a Slack channel.\n\nWHEN TO USE: Triage — finding the last alert in a channel, "
            "or pulling context for a current decision.\n\nRETURNS: Array of messages with text + ts + user.\n\n"
            "NOTE: Requires the bot to be in the channel. Conversation history scope required."
        ),
        json_schema=_schema({"channel": {"type": "string"}, "limit": {"type": "integer"}, "oldest_ts": {"type": "string"}},
                            required=["channel"]),
    ),
    Tool(
        name="notion_page_create",
        toolbox="github",
        description=(
            "Create a new Notion page under a parent (database or page).\n\nWHEN TO USE: Adding a new row to a "
            "Notion database, or creating a new doc page.\n\nRETURNS: New page id + URL.\n\n"
            "NOTE: For Confluence pages use confluence_page_create — separate system."
        ),
        json_schema=_schema({
            "parent": {"type": "object"}, "properties": {"type": "object"}, "children": {"type": "array"},
        }, required=["parent", "properties"]),
    ),
    Tool(
        name="notion_database_query",
        toolbox="github",
        description=(
            "Query a Notion database with filters and sorts.\n\nWHEN TO USE: Pulling rows from a Notion-backed table "
            "(tasks, OKRs, etc).\n\nRETURNS: Array of pages matching the filter.\n\n"
            "NOTE: Filter syntax is Notion-specific JSON; see Notion API docs."
        ),
        json_schema=_schema({
            "database_id": _ID, "filter": {"type": "object"}, "sorts": {"type": "array"},
            "page_size": {"type": "integer"},
        }, required=["database_id"]),
    ),
    Tool(
        name="sentry_event_get",
        toolbox="github",
        description=(
            "Fetch one Sentry event by id with full stack trace and breadcrumbs.\n\n"
            "WHEN TO USE: Investigating a production error — pulling the exact stack and request context.\n\n"
            "RETURNS: Event object with exception, breadcrumbs, contexts.\n\nNOTE: For aggregated issue view, use sentry_issue_get."
        ),
        json_schema=_schema({"organization_slug": {"type": "string"}, "event_id": _ID},
                            required=["organization_slug", "event_id"]),
    ),
    Tool(
        name="sentry_issue_resolve",
        toolbox="github",
        description=(
            "Mark a Sentry issue (a grouping of similar events) as resolved.\n\n"
            "WHEN TO USE: After deploying a fix, marking the underlying issue resolved so it doesn't keep alerting.\n\n"
            "RETURNS: Updated issue with status=resolved.\n\nNOTE: Sentry will re-open if the same fingerprint recurs after resolution."
        ),
        json_schema=_schema({"organization_slug": {"type": "string"}, "issue_id": _ID},
                            required=["organization_slug", "issue_id"]),
    ),
    Tool(
        name="sentry_alert_silence",
        toolbox="github",
        description=(
            "Silence a Sentry alert rule for a duration.\n\nWHEN TO USE: Maintenance windows; or while a fix is in flight "
            "and you don't want to spam the channel.\n\nRETURNS: Snooze object.\n\nNOTE: Use organization slug + alert rule id."
        ),
        json_schema=_schema({
            "organization_slug": {"type": "string"}, "alert_rule_id": _ID,
            "until": {"type": "string", "description": "ISO 8601 timestamp when silencing ends."},
        }, required=["organization_slug", "alert_rule_id"]),
    ),
)


# ---------- Public pool ----------

# Ordered so that early indices give realistic GitHub-MCP-style distractors;
# the multi-MCP (Linear/Atlassian/Slack) tools come at the end and only appear
# at the 150-tool catalog size.

DISTRACTOR_POOL: tuple[Tool, ...] = (
    *GH_ACTIONS,        # 15 tools
    *GH_SECRETS,        # 10 tools
    *GH_SECURITY,       # 12 tools
    *GH_PR_EXTRAS,      # 12 tools — includes the real confusables from #476, #582, #1214
    *GH_ADMIN,          # 10 tools
    *GH_MISC,           # 15 tools
    *FS_EXTRAS,         # 10 tools
    *GIT_EXTRAS,        # 10 tools
    *LINEAR_ATLASSIAN,  # 20 tools — multi-MCP feel
)

# Sanity check on import — fail fast if the count drifts
assert len(DISTRACTOR_POOL) == 114, f"distractor pool size = {len(DISTRACTOR_POOL)}"
