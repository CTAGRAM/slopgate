**Outside contributors: 34 real pull requests from 15 repositories**, 33 that maintainers labelled `spam` and 1 merged PRs from the same repositories.

| Contender | Kind | Judged | Spam caught (recall) | Precision | Spam fast-tracked | False alarms on merged PRs | Median time | Model time | Tokens / PR |
|---|---|---|---|---|---|---|---|---|---|
| SlopGate · OpenJev | System One | 34/34 | 52% | 100% | 3% | 0% | 1.8 s | 238 ms | 1817 |
| SlopGate · Clef-flash | System One | 34/34 | 30% | 100% | 18% | 0% | 1.2 s | 136 ms | 2302 |
| DiffusionGemma 26B as chat | Chat LLM | 34/34 | 36% | 100% | 27% | 0% | 1.2 s | 343 ms | 1571 |
| CodeRabbit | Observed | 1/34 | 100% | 100% | - | - | 6.7 min | - | - |

**Everyone: 101 real pull requests from 29 repositories**, 60 that maintainers labelled `spam` and 41 merged PRs from the same repositories.

| Contender | Kind | Judged | Spam caught (recall) | Precision | Spam fast-tracked | False alarms on merged PRs | Median time | Model time | Tokens / PR |
|---|---|---|---|---|---|---|---|---|---|
| SlopGate · OpenJev | System One | 101/101 | 28% | 100% | 3% | 0% | 1.2 s | 214 ms | 1937 |
| SlopGate · Clef-flash | System One | 101/101 | 17% | 100% | 15% | 0% | 1.1 s | 127 ms | 2435 |
| DiffusionGemma 26B as chat | Chat LLM | 98/101 | 22% | 93% | 29% | 2% | 1.2 s | 342 ms | 1683 |
| CodeRabbit | Observed | 2/101 | 100% | 100% | - | 0% | 3.7 min | - | - |
