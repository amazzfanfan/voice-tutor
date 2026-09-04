# Turn Classifier

Classify the current voice turn before retrieval.

## Inputs

Conversation history:

{{history_context}}

Current user input:

{{query}}

## Labels

- `knowledge_query`: The learner asks a new technical or industrial learning question, or gives a short but meaningful technical term.
- `profile_reply`: The learner is answering a previously asked role, background, purpose, or usage-scenario question.
- `followup_query`: The learner asks a follow-up about the current technical topic.
- `conversation_control`: The learner is controlling pacing, asking to pause, slow down, repeat, or otherwise manage the voice interaction rather than asking for knowledge.
- `unclear_or_noise`: The input is probably speech-recognition noise, an incomplete fragment, or too unrelated/low-information to act on.
- `direct_answer_request`: The learner declines profile collection or explicitly asks for a direct general answer.

Use semantic fit with the conversation, not a fixed keyword list. First identify the primary technical object and learning intent in the latest tutor explanation, then identify them in the current user input.

- Choose `followup_query` only when the current input keeps the same primary equipment, component, material, process, rule, parameter, or causal chain and asks to expand, explain, apply, compare within that object, or resolve an omitted reference from the latest explanation.
- Choose `knowledge_query` when the current input introduces a self-contained different technical object or task. A conversational connector such as “那、另外、顺便、再问一下” does not make it a follow-up when the equipment, material, process, standard, or work target has changed.
- Do not treat “both are industrial questions” or “the sentence sounds connected” as sufficient evidence of a follow-up.
- If the latest explanation is about electric-locomotive overload, “为什么制动距离会变长” is `followup_query`, while “那圆锥破碎机的润滑怎么检查” is `knowledge_query` because the primary equipment and task have changed.
- When the current input could stand alone as a complete question about a different named object, prefer `knowledge_query`. When it contains an omitted subject that can only be resolved from the latest explanation, prefer `followup_query`.

## Output

Only output JSON:

```json
{"turn_type": "knowledge_query|profile_reply|followup_query|conversation_control|unclear_or_noise|direct_answer_request", "reason": "brief reason"}
```
