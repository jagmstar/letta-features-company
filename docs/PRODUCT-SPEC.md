# Product Spec: Skills Management and Installation

## Feature name
**Skills Management and Installation**

## Feature description
Add a dedicated Skills area in Letta Desktop that lets users discover, inspect, install, update, enable, disable, and remove agent skills. Skills are capability packs that extend what an agent can do, and this feature turns the public skill concept into a productized workflow inside the app.

This is the best next feature because it is foundational, expands Letta’s platform value, and creates a path toward future monetization through premium skills, team-shared skills, and a skills marketplace.

---

## User stories and acceptance criteria

### 1) Discover available skills
**User story:** As a user, I want to browse available skills so I can quickly find capabilities that fit my workflow.

**Acceptance criteria:**
- A Skills library page is available in desktop.
- Skills are shown with name, description, category, source, and install status.
- Users can search and filter skills by keyword and category.
- The page supports empty, loading, and error states.

### 2) Inspect a skill before installing
**User story:** As a user, I want to view details for a skill before I install it so I can understand what it does and whether it is safe to use.

**Acceptance criteria:**
- Each skill has a detail view.
- The detail view shows the skill description, version, author/source, required permissions, supported tools, and usage examples.
- The UI clearly indicates whether the skill is verified, external, or custom.
- Users can navigate back to the library without losing their search context.

### 3) Install a skill from a link or registry entry
**User story:** As a user, I want to install a skill from a skill link or catalog entry so I can add new capabilities without manual setup.

**Acceptance criteria:**
- Users can install a skill from a catalog item or pasted skill URL.
- The installer validates the source before completing installation.
- Installation shows progress and returns a success or failure state.
- Installed skills become available to the relevant agent immediately or after a clear refresh action.

### 4) Manage installed skills
**User story:** As a user, I want to enable, disable, and uninstall installed skills so I can control what my agent can do.

**Acceptance criteria:**
- Installed skills appear in a dedicated management view.
- Users can enable or disable a skill without uninstalling it.
- Users can uninstall a skill and confirm the action before removal.
- Disabled or uninstalled skills are no longer exposed to the agent.

### 5) Update skills safely
**User story:** As a user, I want to update installed skills so I can receive improvements and fixes without breaking my setup.

**Acceptance criteria:**
- The app shows when an update is available.
- Users can review release notes before updating.
- Updates preserve the skill’s installation state and configuration when possible.
- If an update is incompatible, the UI warns the user and prevents silent breakage.

### 6) Assign skills to an agent
**User story:** As a user, I want to attach skills to an agent so the agent can use the capabilities I installed.

**Acceptance criteria:**
- Users can assign and remove skills from a specific agent.
- The agent configuration shows all active skills.
- The agent only has access to the tools and behaviors granted by installed skills.
- Changes to agent skills are reflected in the next interaction without requiring a full reconfiguration.

### 7) Share and reuse skills across teams
**User story:** As a team user, I want to share a skill link or import a shared skill so the same capability can be reused across agents and teammates.

**Acceptance criteria:**
- A skill can be imported from a shared link or internal reference.
- Shared skills retain origin metadata and version information.
- The app surfaces whether a skill is personal, team-shared, or public.
- Imported shared skills respect access controls and permissions.

---

## Technical requirements

- Define a stable skill manifest schema with metadata, versioning, permissions, dependencies, and install source.
- Build a skill registry interface for public, team, and local skills.
- Implement install/update/uninstall workflows with validation and rollback support.
- Store installed skill state per user and per agent.
- Add a permission model so skills can declare which tools and capabilities they require.
- Ensure skills are sandboxed or otherwise constrained so they cannot grant unexpected access.
- Add audit logging for install, update, disable, and uninstall actions.
- Support error handling for invalid links, incompatible versions, and network failures.
- Provide analytics hooks for installs, activations, and failures.

---

## Success metrics

- **Adoption:** at least 30% of active desktop users install one skill within 30 days of release.
- **Activation:** at least 70% of installed skills are assigned to an agent after installation.
- **Retention:** at least 50% of users who install a skill return to use it again within 14 days.
- **Reliability:** skill install success rate above 95% for valid sources.
- **Efficiency:** median time to install a skill under 2 minutes from discovery to activation.
- **Revenue signal:** increase in paid/team-plan conversions tied to shared or premium skills.

---

## Timeline estimate

**MVP: 4-6 weeks**
- Week 1: finalize manifest schema, registry shape, and UX flow.
- Week 2: build Skills library and detail views.
- Week 3: implement install/uninstall and state persistence.
- Week 4: add agent assignment, validation, and error handling.
- Week 5-6: polish, analytics, security review, and bug fixes.

**Stretch goals: 2 additional weeks**
- Update/rollback flow improvements.
- Team sharing controls.
- Verified/public skill badges.

---

## Risk assessment

- **Security risk:** skills may request powerful permissions. Mitigation: explicit permission prompts, source validation, and sandboxing.
- **Ecosystem quality risk:** a weak skill catalog can reduce trust. Mitigation: verification badges, curated defaults, and clear metadata.
- **Versioning risk:** updates may break existing agent setups. Mitigation: compatibility checks, rollback support, and release notes.
- **UX risk:** skills can become confusing if the install and assignment flow is too abstract. Mitigation: keep the flow linear and show clear agent impact.
- **Platform risk:** the underlying skill format may evolve as Letta’s public skill model changes. Mitigation: keep the manifest schema extensible and isolated behind an adapter layer.
