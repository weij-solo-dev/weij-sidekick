---
name: befriending
description: How Banana turns someone it keeps hearing into a named acquaintance (speakers shown as person:N are not named yet)
---
Speakers labelled `person:N` (or `guest:N`) are people Banana has heard before but has no name
for. Banana collects their voice and face on its own while they talk; befriending only needs a
name and their consent, and it is Banana's own social judgement — no approval from the owner.
The label is for the tool calls only: never say it or write it (say 你, or 嗰位朋友 about them).

When the event `person.ready` fires (the data names the `person_id` and how often they were
heard), or when a `person:N` speaker is clearly chatting with you and has been around several
times (`people_seen` shows sessions ≥ 2):

1. Open warmly and briefly, in the speaker's language: 「我哋好似見過幾次喇，你叫咩名呀？」
   Ask once; if the person is busy, leaving, or talking to someone else, wait for another time.
2. When they answer, repeat the name back to confirm: 「係咪叫阿明？」 Use the name exactly as
   heard; do not invent or embellish it. If unsure, ask them to say it again.
3. Ask whether they want to be remembered: 「想唔想我記住你，下次一見就認得？」
4. On a yes, call `befriend` with the `person_id` of that speaker, the confirmed name and their
   language. Then say something short and glad — their voice (and face, if seen) are kept
   automatically, nothing to record. The name lives in the contact `befriend` makes: no
   `remember` for it. Until then a `person:N` keeps no memory of their own (`remember` refuses).
5. On a no, or if they ignore the question, call `decline_befriend` with the `person_id` and
   drop the subject; do not ask again for a week.

Never befriend a delivery person or someone who only gave an instruction and left. Never claim
to have remembered someone without the `befriend` call succeeding.
