# Profile Policy

This Skill uses a one-time learner profile gate for voice tutoring.

## Session State Expected From The Host

- `profile_status`: `unknown`, `asked`, `collected`, or `declined`.
- `pending_topic`: the first substantive learning request that triggered the profile question.
- `learner_profile`: role, experience, intended use, and usage scenario when available.

## Rules

1. When the first substantive learning request arrives and no role or usage scenario is known, ask for both in one natural sentence and wait.
2. The host should keep the learner's original request as `pending_topic`; do not discard it just because the next user turn contains only role or scenario information.
3. When the learner supplies profile information, answer `pending_topic` immediately using the profile. Do not treat the profile reply as a new topic.
4. Ask for profile information only once per session. After `profile_status` becomes `collected` or `declined`, continue without repeating the profile question.
5. If the learner later changes role, scenario, or purpose, update the profile silently and use the new context.
6. If the learner declines or asks for a direct answer, set `profile_status` to `declined` and use a neutral industrial explanation.

## Learner-Facing Profile Question

Use one compact sentence:

> 为了给你讲得更贴合，我先问一句：你现在是什么岗位，这个问题主要会用在什么场景？

Do not include a definition, summary, or partial answer in the same turn.
