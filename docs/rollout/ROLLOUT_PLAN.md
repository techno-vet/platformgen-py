# Auger SRE Platform — Rollout Plan

**Version:** 1.0 (Alpha)
**Audience:** ASSIST Program Management, GSA IT
**Status:** Draft for Socialization

---

## Rollout Philosophy

Auger rolls out in three phases with a hard gate at each phase: the platform must prove value and stability at each tier before expanding. Stakeholders (GSA IT, program leadership) are involved at the socialization phase before broad rollout begins.

---

## Current Status: Alpha

- **Who:** ASSIST SRE team (3–5 users)
- **Purpose:** Prove core workflows, fix bugs, build confidence
- **Channel:** Auger POC GChat space (all updates posted there)
- **Branch:** `feature/ASSIST3-38045-alpha-testing-prompts-help-wizard`

---

## Phase 1: Alpha (Current → Q2 2026)

**Goal:** Validate core workflows with SRE team. Harden the platform.

### Success Criteria
- [ ] Story→Prod pipeline used for 10+ real deployments
- [ ] K8s Explorer used as primary log/debug tool for 30 days
- [ ] Zero data-loss incidents from Auger-initiated git commits
- [ ] GChat @mention routing tested for all 10 block event types
- [ ] Flux PR promotion flow used for 3+ STAGING and 1+ PROD promotions

### Widgets in Scope
- Story→Prod, K8s Explorer, Pods, Flux Config, GChat, Jira, Tasks, Ask Auger, Shell Terminal, Database

### Alpha Testing Activities
- Daily use by SRE team — track issues in Jira under ASSIST3-38045
- Biweekly alpha retrospective (SRE + PO)
- Bug reports triaged within 24 hours
- Prompts/help content written and tested with Help Viewer

### Exit Criteria for Alpha
- All P1 bugs resolved
- Core widgets have help content
- Installation guide validated by one team member who wasn't involved in development
- Auger can autonomously drive at least one full story-to-prod cycle with @mention handoffs

---

## Phase 2: Beta (Q2–Q3 2026)

**Goal:** Expand to developer teams. Validate self-service installation.

### Who
- 2–3 ASSIST developer teams (front-end, back-end, data services)
- Release managers
- Product owners (read-only story→prod view)

### Prerequisites
- Alpha exit criteria met
- GSA IT socialization completed (see Phase 0)
- Installation documented and tested for fresh workstation setup
- Role-based permissions model defined (what each role can see/do)

### New Capabilities Targeting Beta
- Panner Phase 1: auto-source DataDog + kubectl panoramic view
- Networked Auger: GChat replies flow back into Auger context (bidirectional)
- IDE integration: Auger can open a file/PR in VS Code from the Dev stage
- Story→Prod Phase 2: pause/resume on block, AI deployment doc generation

### Exit Criteria for Beta
- 3+ developer teams actively using Story→Prod for sprint work
- Self-service installation completed by 5+ users without SRE assistance
- NPS score ≥ 7 from beta user survey
- No P1 security findings from GSA IT review

---

## Phase 3: General Availability (Q3–Q4 2026)

**Goal:** All ASSIST teams with ATO coverage, centralized deployment, managed updates.

### Who
- All ASSIST program teams
- Optionally: other GSA programs (pending IT approval)

### Delivery Model
- Containerized deployment (Docker/Podman) or pip-installable package
- Central updates pushed via Flux (Auger updates itself)
- Credentials provisioned via GSA secrets management

### ATO Considerations
- Document all external network calls (currently: none — all GSA-internal)
- Security scan of container image via Prospector
- Change management process for Auger updates (same Flux PR workflow)
- User access controlled by GHE team membership + `.env` scoped credentials

---

## Phase 0: GSA IT Socialization (Parallel Track, Now)

**Goal:** Inform and align with GSA IT before broader rollout.

### Activities
1. **Brief GSA IT leadership** — share ROLLOUT_GSA_IT_BRIEF.md
2. **Security review** — share ROLLOUT_SECURITY_PRIVACY.md
3. **Demonstrate** — live demo of Story→Prod and K8s Explorer to IT stakeholders
4. **Address concerns** — particularly around AI usage, data handling, GHE API automation
5. **Get informal sign-off** before Phase 2 begins

### Key Messages for GSA IT
- All compute stays within the GSA network boundary
- No AI calls leave GSA (Ask Auger uses internal LLM or self-hosted model)
- Auger automates GHE commits — all actions are auditable in git history
- Credentials never stored in code — local `.env` only
- The platform is built and maintained by the ASSIST SRE team, not a vendor

---

## Rollout Timeline Summary

| Phase | Target Start | Target End | Key Milestone |
|-------|-------------|-----------|---------------|
| Alpha | Mar 2026 (now) | Jun 2026 | 10 real deployments, zero P1 bugs |
| GSA IT Socialization | Apr 2026 | May 2026 | Informal sign-off from IT leadership |
| Beta | Jun 2026 | Sep 2026 | 3+ dev teams, self-service install |
| GA | Oct 2026 | Dec 2026 | All ASSIST teams, ATO coverage |

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Local git objects permission issue persists | High | Medium | All commits use GHE API — already implemented |
| GSA IT blocks AI tooling | Medium | High | Emphasize internal boundary, no external AI calls |
| Developer adoption resistance | Medium | Medium | Focus on Story→Prod visibility — zero learning curve |
| Flux PR 2-approval bottleneck | Low | Low | Enforced by platform — already the correct process |
| Widget breaking with ASSIST API changes | Medium | Medium | Integration tests, hot-reload for fast fixes |

---

*Document generated by Auger AI · ASSIST SRE Platform · Draft v1.0*
