# Architecture

V1.0 keeps evaluation responsibilities explicit:

System Under Test → Evaluation Adapter → Case Execution → Graders → Statistical Analysis → Regression Gate → Report.

The framework separates case definition from execution, grading, statistical interpretation, and release gating.

A system adapter owns invocation. Graders consume the case and observed output. Statistical utilities operate on preserved numeric observations. Regression rules compare a new run against an explicit baseline.

The model-judge interface is provider-neutral. FakeJudge exists only as a deterministic test fixture; it is not evidence of external LLM judge quality.
