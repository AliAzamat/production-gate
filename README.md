# OpenAI | Production Gate — An Enterprise Agent With Graders and Guardrails

An advanced applied-AI capstone about the gap between a demo and a deployment. You pick one workflow with a measurable business outcome, write the success criteria before the code, build a representative eval set including the ugly cases, implement rule-based and model-based graders and validate the graders themselves against human labels, then build a tool-calling agent over a permissioned corpus where a user can never retrieve a document their role cannot access. You instrument every call with latency, tokens, cost, and a trace; enforce a budget in code rather than in a dashboard; and gate deploys on eval regression. The deliverable is the apparatus that makes the system approvable, not the agent.

Built step-by-step with [KhwajaLabs Build](https://khwajalabs.com).

## Stack
- Python
- TypeScript
- tool-calling agents
- permissioned retrieval
- eval graders
- observability
