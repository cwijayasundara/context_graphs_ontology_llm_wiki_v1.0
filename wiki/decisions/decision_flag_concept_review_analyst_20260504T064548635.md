---
id: "decision_flag_concept_review_analyst_20260504T064548635"
type: "Decision"
sources: ["action:flag_concept_review", "actor:analyst"]
confidence: 0.99
updated: "2026-05-04"
ts: "2026-05-04T06:45:48.635866+00:00"
actor: "analyst"
action_id: "flag_concept_review"
scopes: ["any_authenticated"]
approved: false
decision_class: "review_flag"
action_outcome: "ok"
inputs_summary: "{\"concept_id\": \"gross-margin\", \"reason\": \"contradiction\", \"detail\": \"flagged by intel memo 'Intel Memo: nvidia-corp'; hops=2\"}"
result_summary: "{\"concept_id\": \"gross-margin\", \"reason\": \"contradiction\", \"detail\": \"flagged by intel memo 'Intel Memo: nvidia-corp'; hops=2\", \"queue\": \"graph/review_queue.jsonl\", \"duplicate\": false}"
wiki_fingerprint: "15ad6b9bb8c222e33c0334a653e296f1b3f07c695a5116850ce28e6ad3161c22"
ontology_fingerprint: "ac4cf4bf946e1221263dc6004e5a7666b9e0a429a5e076a608f11bde1b1b6994"
links: [{"to": "gross-margin", "type": "affects"}]
---

# flag_concept_review @ 2026-05-04T06:45:48.635866+00:00

_Decision auto-recorded by the action server._

- **Action:** `flag_concept_review`
- **Actor:** analyst
- **Scopes:** any_authenticated
- **Approved:** False
- **Class:** review_flag
- **Outcome:** ok

## Inputs

```json
{"concept_id": "gross-margin", "reason": "contradiction", "detail": "flagged by intel memo 'Intel Memo: nvidia-corp'; hops=2"}
```

## Result

```json
{"concept_id": "gross-margin", "reason": "contradiction", "detail": "flagged by intel memo 'Intel Memo: nvidia-corp'; hops=2", "queue": "graph/review_queue.jsonl", "duplicate": false}
```

