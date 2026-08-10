"""DeepSeek provider-local policy.

There is deliberately no ``DeepSeekAdapter``: DeepSeek runs on the shared
``OpenAIAdapter`` transport. Only the parts that are genuinely DeepSeek —
which models exist, which effort levels each really has on each wire, what an
omitted level means, and the exact payload shape — live here.
"""
