**101 real pull requests from 29 repositories**: 60 that maintainers labelled `spam`, and 41 merged PRs from the same repositories.

| Contender | Kind | Judged | Spam caught (recall) | Precision | Spam fast-tracked | False alarms on merged PRs | Median time | Model time | Tokens / PR |
|---|---|---|---|---|---|---|---|---|---|
| SlopGate · OpenJev | System One | 101/101 | 22% | 87% | 3% | 5% | 1.1 s | 293 ms | 1972 |
| SlopGate · Clef-flash | System One | 101/101 | 23% | 93% | 22% | 2% | 989 ms | 135 ms | 2484 |
| DiffusionGemma 26B as chat | Chat LLM | 100/101 | 23% | 93% | 23% | 2% | 1.3 s | 442 ms | 1732 |
| CodeRabbit | Observed | 2/101 | 100% | 100% | - | 0% | 3.7 min | - | - |
