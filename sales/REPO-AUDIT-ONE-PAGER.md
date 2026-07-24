# AI-SDLC Repo Audit
## Professional repo audit reports for GitHub codebases

**Positioning:** a fast, practical audit of a client's GitHub repository that turns the codebase into a clear risk-and-opportunity report a founder, CTO, or engineering lead can act on immediately.

## What it is

The AI-SDLC Repo Audit is a paid, one-off assessment of a GitHub repository. We clone the repo, analyze the code and delivery surface, and deliver a professional report that highlights strengths, risks, and the highest-value next actions.

This is built to be sold by Roman directly, with no paid tooling required.

## What the client gets

- A polished **markdown report**
- A machine-readable **JSON metrics file**
- Findings across:
  - code quality
  - test coverage
  - security issues
  - documentation
  - CI/CD
  - dependency health
  - license compliance
- A prioritized summary of what to fix first
- Optional fix work if the client wants remediation after the audit

## How it works

1. Client sends a GitHub repo URL.
2. We clone the repo and run the audit pipeline.
3. We review the findings and package them into a client-ready report.
4. We deliver the report and, if requested, implement fixes.

## Pricing

### Basic audit — **$300**
Best for a quick decision-support review.

Includes:
- cloned repo analysis
- audit report
- JSON metrics
- top findings and recommended next steps

### Audit + fixes — **$1K to $3K**
Best for clients who want the issues actually resolved.

Includes:
- everything in the basic audit
- prioritized remediation work
- follow-up validation after fixes
- final updated report

## Turnaround time

- **Basic audit:** 1–2 business days
- **Audit + fixes:** 2–5 business days depending on repo size and issue count

## Why clients buy this

- They want a fast, credible view of repository risk before a release, handoff, acquisition, or investment event.
- They need something more concrete than a gut feel, but lighter than a full consulting engagement.
- They want a clean report they can share internally.

## Demo audit sample findings

Demo run against `jagmstar/letta-features-company` produced:

- **Overall score:** 50.8 / 100, elevated risk
- **License gap:** no LICENSE or COPYING file found
- **Dependency gap:** no dependency manifest detected; 2 external imports were identified (`pytest`, `psutil`)
- **Coverage gap:** test coverage measured at 2.3% across the source set in the current audit run
- **Documentation gap:** module docstring coverage was 14.81% (4 of 27 Python files)
- **Code quality note:** the longest function was 357 lines, and the highest observed cyclomatic complexity was 23
- **Security review:** 7 credential-shaped patterns and 2 shell invocation sites were flagged for review
- **CI/CD strength:** GitHub Actions is present for CI and Pages deployment

## Ideal buyers

- founders preparing for diligence
- CTOs reviewing inherited code
- startups selling to enterprise customers who want a repo-level trust signal
- teams that need a quick technical health check before committing to a project

## Sales close

If a client wants a simple answer to “How healthy is this repo, and what should we fix first?”, this audit gives them a concrete report with real numbers.

**Contact:** Roman

