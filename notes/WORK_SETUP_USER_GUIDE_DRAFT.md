# Set up Swarmkit for your work

**UX draft for review.** This describes a proposed experience, not the current
release. Work profiles, automatic review assignment, the example `profile`
commands, and `init --profile` are not implemented. Example setup results and
reports below are illustrations, not results from your machine.

## What you are setting up

You already have an agent that knows how to work at your company. You want
Swarmkit to coordinate longer assignments through that agent and remember how
you like work handled.

You will save a **work profile**: your environment settings and your usual work
preferences. For example:

> Use my work agent, its internal checkout tools, and its adversarial-review
> skill. Run my review routine for every code change produced by a mission.

You set this up once. Later, you give a mission to your agent using that profile.
You do not need to predict the changes it will produce or attach a review
procedure to each one.

In this guide, a **change** means a related set of code edits that you would
review together. It can be a local change or a change tracked by your company's
review system. Your company may use another name; Swarmkit can display that name.
It does not have to be a Git branch or a pull request.

## 1. Ask your work agent to set it up

Open the agent you normally use at work, in your usual project. Give it this
assignment:

> Set up Swarmkit for this project and save a profile named `work`.
>
> Use this environment's agent harness and existing tools. We use jj and an
> internal command to create lightweight checkouts. Use the tools and instructions
> you already know; ask me only for details you cannot discover.
>
> For every code change produced by my missions, use the `adversarial-review`
> skill in a fresh context. Address supported findings, do a second fresh review,
> then address remaining findings and run the normal checks.
>
> This is a quality routine. Later edits should not automatically restart the
> reviews. Use judgment if another review would be useful.
>
> Try the setup with a disposable local example and show me what is ready.

Replace the review routine with your own preference if you want one review,
additional specialist reviews, or another sequence.

The setup agent installs the CLI if needed, discovers the harness's invocation
and fresh-session options, and connects the existing checkout and review tools.
It also configures the harness to report changes to Swarmkit as work develops.
That connection is what lets your review routine apply automatically.

You do not need to write adapter code or a policy-pack manifest. The setup agent
can configure an existing integration or prepare a small adapter for the tools
it finds. If the harness cannot support something, it reports the specific gap
instead of calling the setup complete.

## 2. Fill in only what the agent cannot discover

Often, the agent already knows your work environment. When something is missing,
you can point it at a command, skill, or internal guide.

| Missing information | An answer you could give |
|---|---|
| How to create an isolated checkout | “Use the checkout command documented in our developer setup guide.” |
| How to start a fresh agent session | “Use the harness's non-interactive runner; its local help documents session creation.” |
| How code changes are tracked | “Use the same internal review tool and terminology you normally use here.” |
| Which review procedure to use | “Use the installed `adversarial-review` skill.” |
| How to request or check access | “Use our access-request tool and check the request there.” |

Credentials stay with the work tools and their normal authentication. You should
not need to copy secrets into the profile.

The agent should distinguish a missing convenience from a missing capability.
For example, an unavailable access-request integration need not prevent local
code work. An inability to start a fresh review session means the requested
review routine is not ready yet.

## 3. Read the setup summary

The agent returns a short summary such as:

```text
Work profile: work

Project             /work/monorepo
Agent harness       Your existing work harness
Isolated checkouts  Internal checkout command; jj revisions
Code changes        Reported through the work harness
Review skill        adversarial-review
Review routine      Review → address findings → fresh review → final fixes/checks
Later edits         Keep completed reviews; no automatic repeat
Access requests     Existing work tool

Trial result
✓ A disposable checkout was created
✓ A worker ran through the configured harness
✓ Its code change automatically received the review routine
✓ Review sessions started with fresh contexts
✓ Review reports and progress appeared in the mission

Ready for a first mission.
```

“Fresh context” here means a new conversation, given the requirements, code,
and relevant test evidence. It does not resume the implementer's conversation.
For the second independent review, the reviewer first assesses the updated code
without being handed the first review's conclusions.

The trial uses a small local change. Any environment integration that requires
an actual submission or other external action is listed separately if it has
not been exercised. The summary should tell you what was tested and what remains
unverified.

Your profile is stored locally and reused by future missions. You can inspect
its effective settings at any time:

**Proposed command:**

```sh
swarmctl profile show work
```

You can also simply ask your agent, “Show me my Swarmkit work settings.”

## 4. Start a real mission

Tell your agent:

> Use my Swarmkit `work` profile to investigate why the service is slow and fix
> the supported causes. Show comparable before-and-after measurements. Keep all
> changes local for now.

The agent starts a mission with your environment and review preferences. It may
discover that no code change is needed, or that several independent changes are
needed. You do not have to specify those in advance.

If you prefer the terminal, the equivalent starting point would be:

**Proposed command:**

```sh
swarmctl --root /work/missions/service-speed/.swarm init \
  --profile work \
  --objective "Investigate and improve service performance" \
  --success "Comparable measurements demonstrate the improvement" \
  --constraint "Keep all changes local"
```

Then use the existing execution and progress commands:

```sh
swarmctl --root /work/missions/service-speed/.swarm run --max-cycles 20
swarmctl --root /work/missions/service-speed/.swarm report
```

Choose the profile when starting the mission. Its preferences then apply to all
changes produced within that mission. It does not monitor unrelated changes you
or other people create outside Swarmkit.

## 5. Let the review routine follow the work

Suppose the investigation produces two changes: improve request batching and
reduce repeated parsing.

As the harness identifies each change, Swarmkit attaches your review routine.
Once a change is ready to review, Swarmkit schedules the first review. Findings
lead to remediation and the second fresh review, followed by final fixes and
checks. The work and its reports survive a stopped agent or restarted controller.

An example progress update:

```text
Service performance

Request batching
  Implementation complete
  First review: 3 findings addressed
  Second fresh review: 1 finding addressed
  Final checks passed
  Review routine complete

Repeated parsing
  Implementation complete
  First review running

Needs you: nothing
```

You can ask, “What did the reviews catch?” or “Why is the second change waiting?”
Your agent can show the review reports or request an explanation from Swarmkit.
You never need to tell it to apply a policy pack to either change.

### What if the code changes after review?

The completed reviews stay recorded. Later edits do not automatically make the
routine incomplete or schedule another round. The agent may recommend another
review when the scope or risk changes substantially, and you can request one.

Swarmkit may record which revision a review examined to help explain its findings.
That information does not become an exact-revision gate for this routine.

### What if a review cannot run?

The affected change shows that its review is waiting, with a reason such as
“the review skill is unavailable.” Other independent work can continue.

You can have the agent fix the setup, substitute an agreed review method, or say,
“Skip the second review for this change and explain that in the result.” A skipped
review remains visibly skipped; it is not reported as having run.

The routine is an automatic part of the plan, with visible exceptions. It is not
a security or compliance certification, and it does not add a company-side gate
to your review system. Existing tool permissions and company requirements still
apply.

## When work needs access

Your harness uses your company's normal tools to request and inspect access.
Swarmkit records what the mission is waiting for, lets other work continue, and
arranges a later check. You do not need to keep the waiting agent conversation
open; the controller must be running or scheduled for those checks to occur.

If the request needs your decision, the report tells you what is needed and why.
Answer it through your agent; the agent records the answer in the mission. If
access is already authorized and the request is being processed elsewhere, it
appears as an external wait instead of repeatedly asking you for permission.

If that access integration is unavailable, the agent gives you the specific
manual action or link and keeps the work visibly waiting.

## Change your preferences later

Tell your agent:

> Update my `work` profile: use one fresh adversarial review by default, and a
> second review when the first finds substantial issues.

The agent shows the revised routine in plain language and saves it. New missions
use the updated preference. Existing missions keep the settings they started with
so ongoing work does not silently change.

To change an active mission as well, say:

> Use that updated review routine for the remaining work in this mission too.

The agent explains which pending reviews will change. Reviews already completed
remain in the history. You can also give a one-mission exception at the start,
such as “For this investigation, produce a diagnosis only.”

## What to look for while reviewing this draft

The proposed experience asks you to describe your work environment and preferences
once, inspect a concrete setup result, and select that profile for a mission.
Swarmkit then follows the routine as changes emerge.

The main UX choices in this draft are an agent-led setup, one named work profile,
automatic review assignment, and flexible review completion without automatic
re-review after subsequent edits. No new company review-system enforcement is
required for this first version.
