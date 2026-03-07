# Student Persona Flow — Production-Grade Spec (LLM-Optimized)

## Document Purpose
This document defines the **student persona flow** for a multi-tenant online music academy SaaS platform.
It is written for:
- product design
- UX design
- backend workflow design
- agentic/LLM-assisted implementation
- test case generation

This is **not** a marketing narrative.
This is a **state-aware product specification** that covers both the golden path and critical exception paths.

---

## Scope
This document covers the **student** experience only.
It assumes a learner can be one of the following:
- `adult_self_serve_student`
- `child_student_managed_by_guardian`
- `academy_assigned_student`
- `trial_student`

Out of scope for this document:
- guardian/parent operational flow in full detail
- instructor flow in full detail
- academy owner/admin flow in full detail

Where needed, guardian/instructor/admin actions are referenced as external actors.

---

## Design Principles
1. **No dead ends**: every major state must offer a meaningful next action.
2. **Fast time-to-value**: after signup or purchase, the learner reaches the right next step immediately.
3. **State integrity over UI convenience**: progress, completion, attendance, and billing must be driven by explicit states.
4. **Graceful failure handling**: payment failure, missed sessions, delayed reviews, and upload issues are first-class flows.
5. **Child safety and privacy**: any minor-facing experience must support guardian visibility and restricted communication.
6. **Cross-device continuity**: dashboard always answers “what should I do next?”
7. **LLM-readable structure**: flows are expressed as state transitions, not prose alone.

---

## Canonical Student Jobs-To-Be-Done
The student uses the platform to:
- discover and trust an academy
- choose the right course or plan
- attend lessons and practice consistently
- submit work and receive feedback
- join live sessions without friction
- track measurable improvement
- manage account, billing, and notifications
- recover smoothly from interruptions

---

## Core Entities

### Student
Key fields:
- `student_id`
- `tenant_id`
- `account_status`
- `learner_type`
- `guardian_linked` (boolean)
- `notification_preferences`
- `timezone`
- `current_learning_goal`

### Enrollment
Key fields:
- `enrollment_id`
- `student_id`
- `course_id`
- `enrollment_status`
- `access_start_at`
- `access_end_at`
- `completion_percentage`
- `next_lesson_id`

### Lesson Progress
Key fields:
- `lesson_progress_id`
- `student_id`
- `lesson_id`
- `lesson_status`
- `content_consumed`
- `assignment_required`
- `assignment_status`
- `ai_feedback_status`
- `instructor_review_status`
- `completed_at`

### Submission
Key fields:
- `submission_id`
- `student_id`
- `lesson_id`
- `submission_type`
- `submission_status`
- `ai_feedback_status`
- `instructor_review_status`
- `score_or_grade`

### Live Session Attendance
Key fields:
- `session_attendance_id`
- `student_id`
- `session_id`
- `attendance_status`
- `join_time`
- `leave_time`
- `recording_status`
- `notes_status`

### Subscription / Billing
Key fields:
- `billing_profile_id`
- `student_id`
- `plan_type`
- `billing_status`
- `grace_period_ends_at`
- `next_billing_at`

---

## Canonical State Models

### 1) Account Status
Allowed values:
- `invited`
- `registered_unverified`
- `active`
- `suspended`
- `pending_deletion`
- `deleted`

### 2) Enrollment Status
Allowed values:
- `not_enrolled`
- `pending_checkout`
- `payment_processing`
- `active`
- `paused`
- `completed`
- `expired`
- `cancelled`
- `refunded`

### 3) Lesson Status
Allowed values:
- `locked`
- `available`
- `in_progress`
- `awaiting_submission`
- `submitted`
- `awaiting_ai_feedback`
- `awaiting_instructor_review`
- `revision_requested`
- `complete`

### 4) Submission Status
Allowed values:
- `not_started`
- `draft`
- `uploading`
- `submitted`
- `processing`
- `reviewed_by_ai`
- `reviewed_by_instructor`
- `revision_requested`
- `accepted`
- `failed`

### 5) Attendance Status
Allowed values:
- `scheduled`
- `reminded`
- `joined`
- `late_joined`
- `completed`
- `missed`
- `cancelled_by_student`
- `cancelled_by_instructor`
- `rescheduled`

### 6) Billing Status
Allowed values:
- `not_required`
- `trialing`
- `active`
- `past_due`
- `grace_period`
- `payment_failed`
- `cancel_scheduled`
- `cancelled`

---

## Global UX Rules
These rules apply across all stages:
- Dashboard must always show exactly one primary CTA: `Continue learning`, `Join session`, `Complete payment`, `Submit assignment`, or `Resolve issue`.
- Every page must have a visible fallback path: `Back to dashboard`, `Contact support`, or `Message instructor` where allowed.
- For minors, direct communication and visibility rules must honor academy policy and guardian settings.
- A student must never lose access to their last valid next step because of navigation confusion.
- Notifications should be contextual, rate-limited, and preference-aware.

---

# Master Flow Map

```text
ENTRY
  -> discovery
  -> signup/invite acceptance
  -> verification/activation
  -> onboarding
  -> assessment or course selection
  -> enrollment/payment
  -> first lesson
  -> lesson/practice/submission loop
  -> live session loop
  -> progress/milestone loop
  -> renewal/retention/next course
  -> pause/cancel/reactivate
```

---

# Stage 1 — Discovery and Entry

## Goal
Convert interest into trusted account creation without ambiguity.

## Entry States
- anonymous visitor from academy-branded landing page
- invited learner from email or direct link
- returning learner not logged in
- guardian arriving on behalf of child learner

## Primary Surfaces
- academy landing page
- invitation page
- signup page
- login page

## Golden Path
### Transition 1.1
- **Current state**: `anonymous_visitor`
- **Trigger**: student opens branded academy link
- **User action**: reads academy info and clicks `Join`
- **System response**: opens tenant-branded signup or login path
- **Next state**: `signup_started`
- **Failure states**:
  - broken/expired invite link -> show recovery CTA `Request new invite`
  - tenant not found -> show safe generic page + support path

### Transition 1.2
- **Current state**: `signup_started`
- **Trigger**: student submits registration form
- **User action**: enters credentials or social login
- **System response**:
  - create account
  - send verification email if required
  - preserve tenant context
- **Next state**: `registered_unverified` or `active`
- **Failure states**:
  - email already exists -> prompt login/reset, do not dead-end
  - social auth failure -> fallback to password/email
  - weak password/form error -> inline correction without page reset

### Transition 1.3
- **Current state**: `registered_unverified`
- **Trigger**: student clicks verification link
- **User action**: confirms email
- **System response**: activate account and route to onboarding
- **Next state**: `active_unonboarded`
- **Failure states**:
  - link expired -> resend flow
  - already verified -> route to login/dashboard

## Required UX Conditions
- academy branding must persist across entry flow
- page must clarify whether user is joining a specific academy or the generic platform
- if learner is a minor, guardian/legal contact capture must be supported when required by tenant policy

---

# Stage 2 — Activation and Onboarding

## Goal
Turn a newly active account into a ready learner with a clear first next step.

## Entry State
- `active_unonboarded`

## Onboarding Outputs
At minimum, onboarding should capture or infer:
- instrument interest
- skill level
- age band
- timezone
- learning goal
- preferred learning mode: self-paced / live / blended
- guardian link if applicable

## Golden Path
### Transition 2.1
- **Current state**: `active_unonboarded`
- **Trigger**: first post-login session
- **User action**: completes onboarding questions or skips allowed steps
- **System response**:
  - personalize dashboard
  - suggest appropriate course or assessment
  - set initial practice goal defaults
- **Next state**: `onboarding_complete`
- **Failure states**:
  - user skips everything -> show generic recommendations, never blank dashboard
  - required child/guardian fields missing -> block restricted features, surface why clearly

### Transition 2.2
- **Current state**: `onboarding_complete`
- **Trigger**: system has enough info to recommend next step
- **User action**: selects `Take assessment`, `Browse courses`, or `Join assigned course`
- **System response**: route to correct decision path
- **Next state**: `assessment_pending` or `catalog_browsing` or `assigned_course_review`

## Required UX Conditions
- dashboard welcome module must answer: `What do I do first?`
- show one primary CTA and up to two secondary CTAs only
- avoid full-screen setup fatigue

---

# Stage 3 — Assessment and Course Matching

## Goal
Prevent wrong-course enrollment and reduce buyer hesitation.

## Entry States
- `assessment_pending`
- `catalog_browsing`
- `assigned_course_review`

## Golden Path
### Transition 3.1 Assessment Path
- **Current state**: `assessment_pending`
- **Trigger**: student starts placement or readiness check
- **User action**: completes quiz, sample task, or self-assessment
- **System response**: recommend course level with confidence and explanation
- **Next state**: `course_recommended`
- **Failure states**:
  - incomplete assessment -> save progress and allow resume
  - low confidence result -> show 2-3 recommended options instead of false certainty

### Transition 3.2 Browsing Path
- **Current state**: `catalog_browsing`
- **Trigger**: student filters/searches catalog
- **User action**: opens course details
- **System response**: show outcomes, prerequisites, lesson count, instructor, reviews, schedule, pricing, and fit guidance
- **Next state**: `course_detail_viewing`
- **Failure states**:
  - course unavailable in region/timezone -> explain and propose alternatives
  - prerequisites unmet -> block enrollment or warn based on policy

### Transition 3.3 Assigned Course Path
- **Current state**: `assigned_course_review`
- **Trigger**: academy or instructor assigned course
- **User action**: accepts and enters course
- **System response**: create active enrollment if billing/access allows
- **Next state**: `ready_to_enroll` or `enrollment_active`

## Required UX Conditions
- course detail page must answer `Is this right for me?`
- support both self-serve purchase and academy-directed assignment
- recommendation confidence should be visible when AI/logic is used

---

# Stage 4 — Enrollment and Payment

## Goal
Convert intent into access with zero confusion.

## Entry States
- `ready_to_enroll`
- `course_detail_viewing`
- `course_recommended`

## Payment Modes
- free enrollment
- one-time course purchase
- subscription
- bundle/package
- trial
- academy-sponsored access

## Golden Path
### Transition 4.1 Free Enrollment
- **Current state**: `ready_to_enroll`
- **Trigger**: student chooses free course
- **User action**: clicks `Enroll`
- **System response**: create active enrollment and route to first lesson
- **Next state**: `enrollment_active`

### Transition 4.2 Paid Enrollment
- **Current state**: `ready_to_enroll`
- **Trigger**: student chooses paid course or plan
- **User action**: completes checkout
- **System response**:
  - create `pending_checkout`
  - process payment
  - on success create `active` enrollment and billing record
  - redirect to confirmation and first lesson
- **Next state**: `enrollment_active`
- **Failure states**:
  - payment declined -> `payment_failed`
  - 3DS/auth interrupted -> recoverable checkout resume
  - duplicate click -> idempotent payment handling

### Transition 4.3 Trial Start
- **Current state**: `ready_to_enroll`
- **Trigger**: student starts trial
- **User action**: accepts trial terms
- **System response**: grant scoped access, set trial end reminders
- **Next state**: `trial_active`
- **Failure states**:
  - invalid trial eligibility -> explain reason and show paid alternatives

## Required UX Conditions
- after successful enrollment, never dump user back to generic dashboard first
- confirmation page must show `Start lesson now`
- if payment fails, page must provide recovery actions immediately

---

# Stage 5 — First Session Value Capture

## Goal
Get the learner to meaningful value in the first few minutes.

## Entry State
- `enrollment_active`

## Golden Path
### Transition 5.1
- **Current state**: `enrollment_active`
- **Trigger**: first course access
- **User action**: clicks `Start first lesson`
- **System response**:
  - open first eligible lesson
  - show course roadmap
  - mark lesson as `available`
- **Next state**: `first_lesson_opened`

### Transition 5.2
- **Current state**: `first_lesson_opened`
- **Trigger**: student consumes core lesson content
- **User action**: watches/reads lesson and interacts with inline tools
- **System response**: update progress, expose assignment and support resources
- **Next state**: `lesson_in_progress`

## Required UX Conditions
- lesson page must show where the learner is in the course
- inline tools should be accessible without losing lesson context
- avoid overwhelming first-time learners with advanced controls

---

# Stage 6 — Self-Paced Learning Loop

## Goal
Create the repeatable loop: learn -> practice -> submit -> review -> progress.

## Entry States
- `lesson_in_progress`
- `returning_to_continue`

## Canonical Loop
```text
lesson_available
  -> lesson_in_progress
  -> awaiting_submission (if assignment required)
  -> submitted
  -> awaiting_ai_feedback
  -> awaiting_instructor_review
  -> complete OR revision_requested
  -> next lesson available
```

## Golden Path
### Transition 6.1 Lesson Consumption
- **Current state**: `available`
- **Trigger**: learner opens lesson
- **User action**: consumes content
- **System response**: set status to `in_progress`
- **Next state**: `in_progress`

### Transition 6.2 Assignment Submission
- **Current state**: `in_progress` or `awaiting_submission`
- **Trigger**: learner submits recording, text response, or practice evidence
- **User action**: upload/submit
- **System response**:
  - create submission record
  - store artifact
  - set lesson/submission states appropriately
- **Next state**: `submitted`
- **Failure states**:
  - upload failure -> retain draft and allow retry
  - unsupported file format -> show accepted formats inline
  - network interruption -> resumable upload if feasible

### Transition 6.3 AI Feedback
- **Current state**: `submitted`
- **Trigger**: submission accepted by system
- **User action**: waits or stays on page
- **System response**:
  - process AI feedback if supported
  - attach structured feedback
  - notify student when ready
- **Next state**: `awaiting_instructor_review` or `complete` depending on course policy
- **Failure states**:
  - AI processing timeout -> mark `processing_delayed`, do not block instructor review path
  - low-confidence analysis -> show limited feedback with caveat

### Transition 6.4 Instructor Review
- **Current state**: `awaiting_instructor_review`
- **Trigger**: instructor review completed
- **User action**: student opens review notification
- **System response**:
  - attach grade/comments/rubric
  - unlock next step based on policy
- **Next state**:
  - `complete` if accepted
  - `revision_requested` if resubmission needed

## Lesson Completion Rules
A lesson should only be `complete` based on explicit academy policy. Allowed policies:
- `content_only`
- `content_plus_submission`
- `content_plus_ai_feedback`
- `content_plus_instructor_review`

Do **not** hard-code `mark lesson complete` as a universal action.
It must be policy-driven.

## Required UX Conditions
- learner always sees exact current status: `In progress`, `Submitted`, `Under review`, `Needs revision`, `Complete`
- next-step CTA must adapt to state
- feedback should be readable, specific, and actionable

---

# Stage 7 — Practice Habit Loop

## Goal
Support daily or weekly practice outside formal lesson completion.

## Entry States
- `active learner`
- `between lessons`
- `post-session practice assigned`

## Golden Path
### Transition 7.1 Practice Start
- **Current state**: `active learner`
- **Trigger**: student opens practice journal or assigned task
- **User action**: starts practice session
- **System response**: prefill recommended practice items from lesson/session notes
- **Next state**: `practice_active`

### Transition 7.2 Practice Logging
- **Current state**: `practice_active`
- **Trigger**: session ends
- **User action**: logs minutes, focus area, notes, optional recording
- **System response**:
  - save practice record
  - update streak and progress metrics
  - optionally run AI analysis on recording
- **Next state**: `practice_logged`
- **Failure states**:
  - user abandons log -> offer quick-save/minimal log path

## Required UX Conditions
- practice logging should be fast enough for daily use
- progress should show longitudinal improvement, not just vanity streaks
- practice and lesson artifacts should be linked where relevant

---

# Stage 8 — Live Session Loop

## Goal
Make synchronous lessons reliable, low-friction, and connected to the learning system.

## Entry States
- `session_scheduled`
- `session_rescheduled`

## Golden Path
### Transition 8.1 Reminders
- **Current state**: `scheduled`
- **Trigger**: session time approaches
- **User action**: none required
- **System response**:
  - send 24h reminder if enabled
  - send 1h reminder if enabled
  - show `Join` CTA at the right time
- **Next state**: `reminded`

### Transition 8.2 Join Session
- **Current state**: `reminded`
- **Trigger**: student clicks `Join`
- **User action**: enters live room
- **System response**:
  - admit student
  - set attendance to `joined`
  - load session UI
- **Next state**: `joined`
- **Failure states**:
  - browser permissions blocked -> guided fix path
  - connection quality poor -> degrade gracefully, show troubleshooting
  - session not started yet -> waiting room state, not error state

### Transition 8.3 Session End
- **Current state**: `joined`
- **Trigger**: session ends
- **User action**: exits room
- **System response**:
  - mark attendance `completed`
  - start recording processing if enabled
  - post notes/homework when available
- **Next state**: `post_session_pending_assets`

### Transition 8.4 Post-Session Assets
- **Current state**: `post_session_pending_assets`
- **Trigger**: recording and/or notes become available
- **User action**: opens summary
- **System response**:
  - expose recording
  - attach notes and homework
  - link next practice task
- **Next state**: `post_session_complete`
- **Failure states**:
  - recording delayed -> show expected status, notify when ready
  - recording failed -> preserve notes and support ticket path

## Exception Paths
### Missed Session
- if student never joins, set `missed`
- route to recording if available
- offer reschedule or follow-up path based on academy policy

### Instructor Cancelled
- notify immediately
- preserve trust with clear reason if allowed
- offer auto-reschedule, credit, or alternate slot

### Student Cancelled
- enforce cancellation window policy visibly
- if late cancellation, explain consequences before confirmation

## Required UX Conditions
- dashboard must prioritize imminent live sessions above routine lessons
- post-session experience must feed directly into practice or next lesson

---

# Stage 9 — Community and Communication

## Goal
Increase engagement without creating unsafe or chaotic communication patterns.

## Channels
- direct instructor messaging
- course discussion/chat
- academy announcements
- recital/event participation

## Communication Rules
- message permissions must be role- and policy-based
- for minors, guardian visibility/moderation may be required
- avoid unrestricted peer DMs by default unless academy enables them
- announcements must be one-to-many and non-reply unless configured otherwise

## Golden Path
### Transition 9.1 Supportive Instructor Interaction
- **Current state**: learner needs clarification
- **Trigger**: learner clicks `Ask instructor`
- **User action**: sends question
- **System response**: route to correct thread with expected response framing
- **Next state**: `awaiting_reply`

### Transition 9.2 Group Belonging
- **Current state**: enrolled learner
- **Trigger**: learner enters course community
- **User action**: reads/posts within allowed scope
- **System response**: enforce moderation, surface relevant notifications only
- **Next state**: `community_engaged`

## Required UX Conditions
- communication must be accessible but not noisy
- unread counts should be visible
- notification preferences must prevent spam fatigue

---

# Stage 10 — Progress, Milestones, and Next Best Action

## Goal
Turn activity into visible achievement and forward momentum.

## Progress Dimensions
- course completion
- lesson completion
- attendance consistency
- practice consistency
- instructor-reviewed improvement
- milestone achievements/certificates

## Golden Path
### Transition 10.1 Course Completion
- **Current state**: last required lesson or review accepted
- **Trigger**: completion criteria satisfied
- **User action**: none or acknowledge completion
- **System response**:
  - mark enrollment `completed`
  - generate certificate if enabled
  - show celebration and recommended next step
- **Next state**: `course_completed`

### Transition 10.2 Next Recommendation
- **Current state**: `course_completed`
- **Trigger**: learner returns to dashboard or completion page
- **User action**: chooses next course, practice plan, recital, or live program
- **System response**: personalize continuation options
- **Next state**: `retained_active_learner`

## Required UX Conditions
- completion must feel earned, not accidental
- completion page must never be a dead end
- recommendations should reflect level progression and learner goals

---

# Stage 11 — Billing, Subscription, and Access Continuity

## Goal
Make money flows clear while minimizing involuntary churn.

## Entry States
- `billing_active`
- `trial_active`
- `past_due`
- `grace_period`
- `cancel_scheduled`

## Golden Path
### Transition 11.1 Renewal Success
- **Current state**: `billing_active`
- **Trigger**: renewal date
- **User action**: none
- **System response**: charge succeeds, access continues, invoice generated
- **Next state**: `billing_active`

### Transition 11.2 Failed Payment Recovery
- **Current state**: renewal or checkout attempt
- **Trigger**: charge fails
- **User action**: update payment method or retry
- **System response**:
  - set `payment_failed` then `grace_period`
  - notify clearly
  - preserve limited continuity if policy allows
- **Next state**: `billing_active` or `cancelled`

### Transition 11.3 User Cancellation
- **Current state**: `billing_active`
- **Trigger**: learner clicks `Cancel plan`
- **User action**: confirms cancellation
- **System response**:
  - explain effective date
  - preserve access until end of paid term if policy says so
  - offer pause/downgrade where relevant
- **Next state**: `cancel_scheduled` or `cancelled`

## Required UX Conditions
- no surprise charges
- cancellation must be self-serve
- student should always know whether course access is immediate, time-bound, subscription-based, or trial-limited

---

# Stage 12 — Support, Recovery, and Reactivation

## Goal
Recover learners when something goes wrong or they disengage.

## Trigger Categories
- abandoned signup
- abandoned checkout
- inactive after enrollment
- missed live session
- submission stuck under review
- payment failure
- churn risk due to low engagement

## Recovery Flows
### 12.1 Abandoned Signup
- send reminder if consent/policy allows
- preserve tenant context
- route back to exact next step

### 12.2 Abandoned Checkout
- recover cart/intent
- remind with course context, not generic spam

### 12.3 Inactive Learner Re-Engagement
- dashboard should show `Resume lesson X`
- send contextual nudges tied to unfinished work or upcoming session

### 12.4 Review SLA Breach
- if instructor review exceeds SLA, student must see transparent status, not silence
- optionally escalate to support/admin queue

### 12.5 Reactivation After Cancellation or Expiry
- preserve historical progress where policy allows
- make reactivation simpler than first-time enrollment

---

# Critical Exception Matrix

| Scenario | Required System Behavior | Student-Facing Outcome |
|---|---|---|
| Email verification link expired | Regenerate securely | Student can continue without support ticket |
| Payment fails at checkout | Preserve intent, show retry/update method | No confusion about whether purchase succeeded |
| Upload fails during assignment | Keep draft state and allow retry | Student does not lose work |
| AI feedback unavailable | Do not block instructor review unnecessarily | Student still progresses with transparency |
| Instructor review delayed | Surface review status and expected timing | Student does not feel abandoned |
| Student misses live session | Mark missed, route to recording/reschedule policy | Recovery path exists |
| Recording processing delayed | Show pending status and notify when ready | No false promise of immediate availability |
| Subscription goes past due | Grace period + notifications + retry | Reduce involuntary churn |
| Minor account missing guardian requirement | Restrict specific features only | Explain what is blocked and why |
| Course completed | Generate next best action | No dead-end celebration page |

---

# Dashboard Decision Logic
The student dashboard should compute the **single highest-priority CTA** using this order:
1. `Join live session now`
2. `Resolve payment/access issue`
3. `Submit required assignment`
4. `Review feedback / revise submission`
5. `Continue current lesson`
6. `Resume practice plan`
7. `Start recommended next course`

Never show multiple primary CTAs with equal emphasis.

---

# Notification Rules

## Event Types
- invite sent
- account verified
- enrollment confirmed
- payment receipt
- payment failed
- upcoming session reminder
- session changed/cancelled
- submission received
- AI feedback ready
- instructor review ready
- revision requested
- milestone earned
- trial ending
- subscription renewing/cancelled
- inactivity nudge

## Rules
- notifications must map to an actionable destination
- avoid sending both email and push for low-priority events unless explicitly configured
- support guardian copies where required for minors

---

# Analytics / Telemetry Events
Recommended events for implementation and UX monitoring:
- `academy_landing_viewed`
- `signup_started`
- `signup_completed`
- `email_verified`
- `onboarding_completed`
- `assessment_started`
- `assessment_completed`
- `course_detail_viewed`
- `checkout_started`
- `checkout_completed`
- `checkout_failed`
- `lesson_started`
- `lesson_completed`
- `assignment_submitted`
- `ai_feedback_generated`
- `instructor_review_completed`
- `practice_logged`
- `session_joined`
- `session_missed`
- `recording_viewed`
- `course_completed`
- `subscription_cancelled`
- `reactivation_completed`

---

# Acceptance Criteria Summary
A production-ready student flow should satisfy all of the following:
- learner can always identify the next best action
- course access is deterministic and billing-aware
- lesson completion is policy-driven, not guessed
- review and feedback states are explicit
- live session failures have recovery flows
- communication is controlled and safe
- minors are handled with proper restrictions/visibility
- completion always leads to retention or progression options
- every major interruption has a recovery path

---

# Suggested Follow-On Documents
To complete the persona architecture, create these next:
1. `guardian_persona_flow.md`
2. `instructor_persona_flow.md`
3. `academy_owner_persona_flow.md`
4. `student_state_machine.md`
5. `notification_matrix.md`
6. `billing_access_rules.md`
7. `minor_safety_and_communication_policy.md`

---

# Compact LLM Summary
Use this as a quick reasoning reference:

```yaml
student_flow_core:
  entry:
    - discovery
    - invite_acceptance
    - signup
    - verification
  activation:
    - onboarding
    - assessment_or_course_selection
  monetization:
    - free_enroll
    - paid_checkout
    - subscription
    - trial
    - sponsored_access
  learning_loop:
    - lesson_open
    - learn
    - practice
    - submit
    - ai_feedback
    - instructor_review
    - complete_or_revision
    - next_lesson
  live_loop:
    - reminder
    - join
    - attend
    - recording_and_notes
    - followup_practice
  progress_loop:
    - milestone
    - certificate
    - next_recommendation
  recovery:
    - payment_failure
    - missed_session
    - upload_failure
    - delayed_review
    - reactivation
  design_rules:
    - no_dead_ends
    - single_primary_cta
    - explicit_states
    - minor_safety
    - policy_driven_completion
```

