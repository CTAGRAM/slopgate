**101 real pull requests from 29 repositories**: 60 that maintainers labelled `spam`, and 41 merged PRs from the same repositories.

| Contender | Kind | Judged | Spam caught (recall) | Precision | Spam fast-tracked | False alarms on merged PRs | Median time | Model time | Tokens / PR |
|---|---|---|---|---|---|---|---|---|---|
| SlopGate · OpenJev | System One | 101/101 | 25% | 83% | 7% | 7% | 971 ms | 263 ms | 1975 |
| SlopGate · Clef-flash | System One | 101/101 | 23% | 93% | 15% | 2% | 842 ms | 139 ms | 2487 |
| DiffusionGemma 26B as chat | Chat LLM | 100/101 | 22% | 93% | 25% | 2% | 1.1 s | 375 ms | 1731 |
| CodeRabbit | Observed | 2/101 | 100% | 100% | - | 0% | 3.7 min | - | - |
