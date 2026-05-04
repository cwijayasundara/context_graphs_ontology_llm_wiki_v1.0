---
id: "decision_flag_concept_review_analyst_20260504T064548624"
type: "Decision"
sources: ["action:flag_concept_review", "actor:analyst"]
confidence: 0.99
updated: "2026-05-04"
ts: "2026-05-04T06:45:48.624899+00:00"
actor: "analyst"
action_id: "flag_concept_review"
scopes: ["any_authenticated"]
approved: false
decision_class: "review_flag"
action_outcome: "ok"
inputs_summary: "{\"concept_id\": \"gaap\", \"reason\": \"contradiction\", \"detail\": \"flagged by intel memo 'Intel Memo: nvidia-corp'; hops=2\"}"
result_summary: "{\"concept_id\": \"gaap\", \"reason\": \"contradiction\", \"detail\": \"flagged by intel memo 'Intel Memo: nvidia-corp'; hops=2\", \"queue\": \"graph/review_queue.jsonl\", \"duplicate\": false}"
wiki_fingerprint: "5142a32d80efad598680bdddebd214d87d187e1f7749f50982a347c579768f30"
ontology_fingerprint: "ac4cf4bf946e1221263dc6004e5a7666b9e0a429a5e076a608f11bde1b1b6994"
links: [{"to": "gaap", "type": "affects"}]
---

# flag_concept_review @ 2026-05-04T06:45:48.624899+00:00

_Decision auto-recorded by the action server._

- **Action:** `flag_concept_review`
- **Actor:** analyst
- **Scopes:** any_authenticated
- **Approved:** False
- **Class:** review_flag
- **Outcome:** ok

## Inputs

```json
{"concept_id": "gaap", "reason": "contradiction", "detail": "flagged by intel memo 'Intel Memo: nvidia-corp'; hops=2"}
```

## Result

```json
{"concept_id": "gaap", "reason": "contradiction", "detail": "flagged by intel memo 'Intel Memo: nvidia-corp'; hops=2", "queue": "graph/review_queue.jsonl", "duplicate": false}
```

