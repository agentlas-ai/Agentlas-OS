# /hep-upload

Always ask the destination question before doing anything else, even if the
arguments already say upload, publish, add, Cloud, Hub, or a target folder:

```text
Cloud에 업로드 할까요? 다른사람들이 볼 수 없어요.
Upload to Cloud? Other people cannot see it.

Agentlas Hub에 업로드 할까요? 다른 사람들이 빌려 쓸 수 있어요.
Upload to Agentlas Hub? Other people can borrow it.
```

Do not package, publish, register, add-source, reindex, or call an upload API
until the user answers Cloud or Agentlas Hub. Cloud means private-link owner
Cloud upload through `bin/hephaestus publish <agent-folder> --visibility
private-link`. Agentlas Hub means public marketplace upload through
`bin/hephaestus publish <agent-folder> --visibility marketplace` after the
bundled publicProfile, routing-card, hash, static security, and bundle-size
gates pass.
