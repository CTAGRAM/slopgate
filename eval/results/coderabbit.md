**Outside contributors: 25 real pull requests from 14 repositories**, 23 that maintainers labelled `spam` and 2 merged PRs from the same repositories.

| Contender | Kind | Judged | Spam caught (recall) | Precision | Spam fast-tracked | False alarms on merged PRs | Median time | Model time | Tokens / PR |
|---|---|---|---|---|---|---|---|---|---|
| SlopGate · OpenJev | System One | 25/25 | 39% | 90% | 0% | 50% | 1.2 s | 259 ms | 1617 |
| SlopGate · Clef-flash | System One | 25/25 | 17% | 80% | 17% | 50% | 897 ms | 107 ms | 2178 |
| DiffusionGemma 26B as chat | Chat LLM | 24/25 | 18% | 100% | 5% | 0% | 1.1 s | 366 ms | 1370 |
| CodeRabbit | Observed | 17/25 | 7% | 100% | - | 0% | 2.1 min | - | - |
| anti-slop (34 rules) | Rules | 25/25 | 74% | 94% | 26% | 50% | 4.2 s | - | - |

**Everyone: 74 real pull requests from 23 repositories**, 40 that maintainers labelled `spam` and 34 merged PRs from the same repositories.

| Contender | Kind | Judged | Spam caught (recall) | Precision | Spam fast-tracked | False alarms on merged PRs | Median time | Model time | Tokens / PR |
|---|---|---|---|---|---|---|---|---|---|
| SlopGate · OpenJev | System One | 74/74 | 22% | 90% | 2% | 3% | 1.1 s | 314 ms | 1979 |
| SlopGate · Clef-flash | System One | 74/74 | 10% | 80% | 30% | 3% | 899 ms | 134 ms | 2496 |
| DiffusionGemma 26B as chat | Chat LLM | 73/74 | 26% | 100% | 23% | 0% | 1.2 s | 387 ms | 1740 |
| CodeRabbit | Observed | 58/74 | 3% | 100% | - | 0% | 75.5 s | - | - |
| anti-slop (34 rules) | Rules | 74/74 | 48% | 63% | 52% | 32% | 3.7 s | - | - |
