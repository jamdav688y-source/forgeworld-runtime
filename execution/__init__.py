"""Execution-layer support: failure classification and retry policy.

Kept separate from governance/ because these concerns (how do we
interpret a raw failure, is it worth retrying) are about *execution
mechanics*, not about *who may do what* -- but failure_classification.py
feeds directly into governance.pipeline, which is where the two meet.
"""
