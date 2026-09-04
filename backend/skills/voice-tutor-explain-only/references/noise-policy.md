# Noise And Conversation-Control Policy

Before retrieval, decide whether the current input contains an actionable learning request.

## Bypass Retrieval

Bypass Wiki, RAG, and WebSearch when the input appears to be one of these semantic cases:

- Speech-recognition noise or an incomplete fragment.
- A pacing or conversation-control utterance, such as asking the tutor to slow down, pause, continue later, or repeat.
- A minimal backchannel or acknowledgement that does not ask for new information.
- A reply that is clearly unrelated to the current technical topic and does not contain a learnable question.

Do not classify purely by a fixed word list. Use the conversation history and the current utterance's information content. If the input might be a valid short industrial term, treat it as a learning request.

## Learner-Facing Replies

Use a short, calm repair prompt:

- If pacing/control is likely: `好，我慢一点。你可以继续说，或者重新说一下你想问的点。`
- If recognition noise or an incomplete fragment is likely: `我刚才可能没听清，你可以重新说一遍问题。`

Do not mention retrieval, tools, Skill policy, or ASR internals.
